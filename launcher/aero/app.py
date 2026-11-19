"""Aero Arcana launcher window (pywebview): JS <-> Python bridge around aero.core."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback

import webview

from . import core, crash, remote

NICK_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def _timed(fn):
    def w(*a, **k):
        t0 = time.time(); core.log.info("ui> %s start (thread %s)", fn.__name__, threading.current_thread().name)
        try:
            return fn(*a, **k)
        finally:
            core.log.info("ui> %s done %.2fs", fn.__name__, time.time() - t0)
    w.__name__ = fn.__name__
    return w


class Api:
    def __init__(self):
        self._state = core.State()
        self._window = None
        self._busy = False

    # ---- called from JS
    @_timed
    def init(self):
        remote.cleanup_old()
        threading.Thread(target=self._check_update, daemon=True).start()
        s = self._state.settings
        return {
            "nick": s.get("nick", ""),
            "ram": s.get("ram", core.default_ram()),
            "ramMax": max(4, int(core.total_ram_gb()) - 2),
            "join": s.get("join", True),
            "version": core.LAUNCHER_VERSION,
            "pack": self._state.data.get("pack_version", "—"),
            "root": str(core.ROOT),
        }

    @_timed
    def news(self):
        return core.fetch_news()

    @_timed
    def update_info(self):
        return core.launcher_update()

    def open_url(self, url):
        if url.startswith("https://github.com/Nikogrelis/aero-arcana"):
            os.startfile(url)

    @_timed
    def status(self):
        return core.server_status("51.75.74.159", 25501)

    def open_folder(self, which="game"):
        path = core.GAME if which == "game" else core.ROOT / "logs"
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def reinstall(self):
        """Forget installed hashes for mods/configs owned by the pack, so the next start re-checks everything."""
        self._state.data["files"] = {}
        self._state.save()
        return True

    def play(self, nick, ram, join):
        if self._busy:
            return {"ok": False, "error": "Уже запускается"}
        if not NICK_RE.match(nick or ""):
            return {"ok": False, "error": "Ник: 3–16 символов, латиница, цифры и _"}
        self._state.settings.update({"nick": nick, "ram": int(ram), "join": bool(join)})
        self._state.save()
        self._busy = True
        threading.Thread(target=self._run, args=(nick, int(ram), bool(join)), daemon=True).start()
        return {"ok": True}

    # ---- worker
    def _check_update(self):
        try:
            idx = core.fetch_index(self._state)
            if remote.self_update(idx, self._progress):
                self._emit("restarting", {})
                if self._window:
                    self._window.destroy()
                os._exit(0)
        except Exception as e:
            core.log.warning("self-update check failed: %s", e)

    def _emit(self, event, payload):
        if self._window:
            self._window.evaluate_js(f"window.onLauncher({json.dumps(event)}, {json.dumps(payload, ensure_ascii=False)})")

    def _progress(self, stage, frac, text):
        self._emit("progress", {"stage": stage, "frac": frac, "text": text})

    def _run(self, nick, ram, join):
        try:
            idx = core.sync_pack(self._state, self._progress)
            fixed = remote.apply_fixes(idx, self._state, nick)
            if fixed:
                self._progress("sync", 1.0, f"Применены исправления: {len(fixed)}")
            ram = int(self._state.settings.get("ram", ram))
            self._emit("pack", {"version": idx["version"]})

            def started():
                self._emit("started", {})
                if self._window:
                    self._window.minimize()
            t0 = time.time()
            code = core.start_game(idx, nick, ram, self._progress, started, join)
            core.log.info("game exited with %s", code)
            if self._window:
                self._window.restore()
            info = {"code": code, "log": str(core.GAME / "logs" / "latest.log")}
            if crash.is_crash(code, t0):
                self._progress("report", None, "Игра вылетела — отправляю отчёт…")
                r = crash.report(nick, code, t0, idx["version"])
                info.update({"crash": True, "hint": r["hint"], "sent": r["sent"]})
            self._emit("exited", info)
        except Exception as e:
            core.log.error("launch failed: %s\n%s", e, traceback.format_exc())
            sent = False
            try:   # launcher-side failures (downloads, install) are reported too
                sent = crash.report(nick, -1, time.time() - 3600, self._state.data.get("pack_version", "?"), error=str(e))["sent"]
            except Exception as e2:
                core.log.warning("error report failed: %s", e2)
            self._emit("error", {"text": str(e) + ("\n\nОтчёт отправлен владельцу." if sent else "")})
        finally:
            self._busy = False


def inline_ui(index: "os.PathLike") -> str:
    """Embed assets as data: URIs. Loading from pywebview's local HTTP server hung ~20 s on some Windows networks."""
    import base64, pathlib, re as _re
    index = pathlib.Path(index)
    html = index.read_text(encoding="utf-8")
    mime = {".jpg": "image/jpeg", ".png": "image/png", ".ttf": "font/ttf"}

    def data_uri(m):
        f = index.parent / m.group(2)
        return f'{m.group(1)}data:{mime[f.suffix]};base64,{base64.b64encode(f.read_bytes()).decode()}{m.group(3)}'
    return _re.sub(r"""(url\(["']?|src=")(assets/[^"')]+)(["']?\)|")""", data_uri, html)


def main():
    api = Api()
    ui = core.resource("ui/index.html")
    window = webview.create_window("Aero Arcana", html=inline_ui(ui), js_api=api, width=1180, height=700,
                                   min_size=(980, 600), background_color="#0b0d16")
    api._window = window
    window.events.shown += lambda: core.log.info("ui> window shown")
    window.events.loaded += lambda: core.log.info("ui> page loaded")
    core.log.info("ui> start")
    webview.start(gui="edgechromium", debug=bool(os.environ.get("AERO_DEBUG")),
                  private_mode=False, storage_path=str(core.ROOT / "webview"))


def cli():
    """Headless mode for tests: python -m aero.app --cli NICK [--sync-only]"""
    state = core.State()
    pr = lambda st, fr, tx: print(f"[{st}] {'' if fr is None else f'{fr*100:5.1f}% '}{tx}", flush=True)
    idx = core.sync_pack(state, pr)
    if "--sync-only" in sys.argv:
        return
    core.start_game(idx, sys.argv[2], core.default_ram(), pr, lambda: print("[started]", flush=True), False)


if __name__ == "__main__":
    cli() if "--cli" in sys.argv else main()
