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

from . import core, crash

NICK_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


class Api:
    def __init__(self):
        self.state = core.State()
        self.window = None
        self.busy = False

    # ---- called from JS
    def init(self):
        s = self.state.settings
        return {
            "nick": s.get("nick", ""),
            "ram": s.get("ram", core.default_ram()),
            "ramMax": max(4, int(core.total_ram_gb()) - 2),
            "join": s.get("join", True),
            "version": core.LAUNCHER_VERSION,
            "pack": self.state.data.get("pack_version", "—"),
            "root": str(core.ROOT),
        }

    def news(self):
        return core.fetch_news()

    def update_info(self):
        return core.launcher_update()

    def open_url(self, url):
        if url.startswith("https://github.com/Nikogrelis/aero-arcana"):
            os.startfile(url)

    def status(self):
        return core.server_status("51.75.74.159", 25501)

    def open_folder(self, which="game"):
        path = core.GAME if which == "game" else core.ROOT / "logs"
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def reinstall(self):
        """Forget installed hashes for mods/configs owned by the pack, so the next start re-checks everything."""
        self.state.data["files"] = {}
        self.state.save()
        return True

    def play(self, nick, ram, join):
        if self.busy:
            return {"ok": False, "error": "Уже запускается"}
        if not NICK_RE.match(nick or ""):
            return {"ok": False, "error": "Ник: 3–16 символов, латиница, цифры и _"}
        self.state.settings.update({"nick": nick, "ram": int(ram), "join": bool(join)})
        self.state.save()
        self.busy = True
        threading.Thread(target=self._run, args=(nick, int(ram), bool(join)), daemon=True).start()
        return {"ok": True}

    # ---- worker
    def _emit(self, event, payload):
        if self.window:
            self.window.evaluate_js(f"window.onLauncher({json.dumps(event)}, {json.dumps(payload, ensure_ascii=False)})")

    def _progress(self, stage, frac, text):
        self._emit("progress", {"stage": stage, "frac": frac, "text": text})

    def _run(self, nick, ram, join):
        try:
            idx = core.sync_pack(self.state, self._progress)
            self._emit("pack", {"version": idx["version"]})

            def started():
                self._emit("started", {})
                if self.window:
                    self.window.minimize()
            t0 = time.time()
            code = core.start_game(idx, nick, ram, self._progress, started, join)
            core.log.info("game exited with %s", code)
            if self.window:
                self.window.restore()
            info = {"code": code, "log": str(core.GAME / "logs" / "latest.log")}
            if crash.is_crash(code, t0):
                self._progress("report", None, "Игра вылетела — отправляю отчёт…")
                r = crash.report(nick, code, t0, idx["version"])
                info.update({"crash": True, "hint": r["hint"], "sent": r["sent"]})
            self._emit("exited", info)
        except Exception as e:
            core.log.error("launch failed: %s\n%s", e, traceback.format_exc())
            self._emit("error", {"text": str(e)})
        finally:
            self.busy = False


def main():
    api = Api()
    ui = core.resource("ui/index.html")
    window = webview.create_window("Aero Arcana", url=str(ui), js_api=api, width=1180, height=700,
                                   min_size=(980, 600), background_color="#0b0d16")
    api.window = window
    webview.start(gui="edgechromium", debug=bool(os.environ.get("AERO_DEBUG")))


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
