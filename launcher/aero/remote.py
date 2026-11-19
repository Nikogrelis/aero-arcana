"""Remote maintenance: launcher self-update and fixes pushed from pack/index.json.

index.json may contain:
  "launcher": {"version": "1.0.1", "url": ".../AeroArcana.exe", "sha256": "..."}
  "fixes": [
    {"id": "quzai0-no-shaders", "nicks": ["Quzai0"],            # omit "nicks" -> everyone
     "op": "set", "path": "config/iris.properties", "values": {"enableShaders": "false"}},
    {"id": "...", "op": "delete", "path": "config/some.cfg"},
    {"id": "...", "op": "settings", "values": {"ram": 8}}        # launcher settings (ram, join)
  ]
Each fix is applied once per installation (remembered by id in launcher.json).
"set" works for key=value (.properties/.txt/options.txt) and TOML "key = value" files.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

from . import core


# ---------------------------------------------------------------- fixes
def _set_values(path, values: dict) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    toml = path.suffix == ".toml"
    for key, val in values.items():
        if toml:
            v = val if isinstance(val, (bool, int, float)) else f'"{val}"'
            v = str(v).lower() if isinstance(val, bool) else str(v)
            rx = re.compile(rf'^(\s*"?{re.escape(key)}"?\s*=\s*).*$', re.M)
            line_val = v
        else:
            rx = re.compile(rf"^({re.escape(key)}[=:]).*$", re.M)
            line_val = str(val).lower() if isinstance(val, bool) else str(val)
        if rx.search(text):
            text = rx.sub(lambda m: m.group(1) + line_val, text, count=1)
        else:
            text += ("" if text.endswith("\n") or not text else "\n") + (f"{key} = {line_val}" if toml else f"{key}={line_val}") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def apply_fixes(idx: dict, state: "core.State", nick: str) -> list[str]:
    done = state.data.setdefault("fixes_applied", [])
    applied = []
    for fx in idx.get("fixes", []):
        fid = fx.get("id")
        if not fid or fid in done:
            continue
        nicks = fx.get("nicks")
        if nicks and nick not in nicks:
            continue
        try:
            op, rel = fx.get("op"), fx.get("path", "")
            if op in ("set", "delete") and not core.is_safe_rel(rel):
                raise ValueError("unsafe path")
            if op == "set":
                _set_values(core.GAME / rel, fx["values"])
                if rel in state.data["files"]:
                    state.remember(rel)      # the fix is now the 'installed' version, pack updates still apply
            elif op == "delete":
                (core.GAME / rel).unlink(missing_ok=True)
            elif op == "settings":
                state.settings.update({k: v for k, v in fx["values"].items() if k in ("ram", "join")})
            else:
                raise ValueError(f"unknown op {op}")
            done.append(fid)
            applied.append(fid)
            core.log.info("fix applied: %s", fid)
        except Exception as e:
            core.log.warning("fix %s failed: %s", fid, e)
    state.save()
    return applied


# ---------------------------------------------------------------- self-update
def current_exe():
    return sys.executable if getattr(sys, "frozen", False) else None


def cleanup_old() -> None:
    exe = current_exe()
    if exe:
        old = exe + ".old"
        try:
            if os.path.exists(old):
                os.remove(old)
        except OSError:
            pass


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def self_update(idx: dict, progress) -> bool:
    """Download a newer launcher from the manifest, swap the running exe and restart. Returns True if restarting."""
    info = idx.get("launcher") or {}
    exe = current_exe()
    if not exe or not info.get("url") or _ver(info.get("version", "0")) <= _ver(core.LAUNCHER_VERSION):
        return False
    progress("update", None, f"Обновление лаунчера до {info['version']}…")
    data = core.http_get(info["url"], timeout=180)
    if hashlib.sha256(data).hexdigest() != info.get("sha256"):
        core.log.warning("launcher update checksum mismatch, skipped")
        return False
    new = exe + ".new"
    with open(new, "wb") as f:
        f.write(data)
    os.replace(exe, exe + ".old")      # a running exe can be renamed on Windows
    os.replace(new, exe)
    core.log.info("launcher updated to %s, restarting", info["version"])
    subprocess.Popen([exe], close_fds=True, creationflags=0x00000008)  # DETACHED_PROCESS
    return True
