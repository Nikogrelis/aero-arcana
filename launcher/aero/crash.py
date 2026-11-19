"""Crash reports: collect logs after a failed game run, upload them to mclo.gs and notify the pack owner.

Privacy: Windows user names in paths are replaced with <user> before upload; only game/launcher logs are sent.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import time
import urllib.parse
import urllib.request

from . import core

MCLOGS_API = "https://api.mclo.gs/1/log"
MAX_BYTES = 8 * 1024 * 1024
USER_RE = re.compile(r"(?i)([A-Z]:[\\/]+Users[\\/]+)([^\\/\s\"']+)")

# Known causes -> short Russian hint for the player and the owner.
HINTS = [
    (re.compile(r"Creating pipeline for dimension|iris.*shader|ShaderCompile|glsl", re.I),
     "Похоже на шейдеры (Iris). Выключите шейдеры: Настройки → Графика → Пакеты шейдеров."),
    (re.compile(r"OutOfMemoryError|Java heap space|Could not reserve enough space", re.I),
     "Не хватило памяти Java. Добавьте память в лаунчере (ползунок «Память»)."),
    (re.compile(r"EXCEPTION_ACCESS_VIOLATION|atio6axx|nvoglv|ig\d+icd", re.I),
     "Вылет драйвера видеокарты. Обновите драйвер и выключите шейдеры."),
    (re.compile(r"Missing or unsupported mandatory dependencies|requires .* or above", re.I),
     "Не хватает мода-зависимости. Нажмите «Проверить файлы» и запустите снова."),
    (re.compile(r"Mixin apply failed|MixinApplyError|InvalidInjectionException", re.I),
     "Конфликт модов (Mixin). Отчёт отправлен — исправим в сборке."),
]


def scrub(text: str) -> str:
    return USER_RE.sub(r"\1<user>", text)


def _read_tail(p: pathlib.Path) -> str:
    data = p.read_bytes()
    if len(data) > MAX_BYTES:
        data = b"...(truncated)...\n" + data[-MAX_BYTES:]
    return scrub(data.decode("utf-8", "replace"))


def collect(started_at: float) -> dict[str, pathlib.Path]:
    g = core.GAME
    files = {}
    crashes = sorted((g / "crash-reports").glob("crash-*.txt"), key=lambda p: p.stat().st_mtime) if (g / "crash-reports").exists() else []
    if crashes and crashes[-1].stat().st_mtime >= started_at - 5:
        files["crash-report"] = crashes[-1]
    hs = [p for p in list(g.glob("hs_err_pid*.log")) + list(core.ROOT.glob("hs_err_pid*.log")) if p.stat().st_mtime >= started_at - 5]
    if hs:
        files["jvm-crash"] = max(hs, key=lambda p: p.stat().st_mtime)
    for name, p in (("latest.log", g / "logs" / "latest.log"), ("debug.log", g / "logs" / "debug.log"),
                    ("portablemc.log", core.ROOT / "logs" / "portablemc.log"), ("launcher.log", core.ROOT / "logs" / "launcher.log")):
        if p.exists():
            files[name] = p
    return files


def is_crash(code: int, started_at: float) -> bool:
    files = collect(started_at)
    return code != 0 or "crash-report" in files or "jvm-crash" in files


def upload(text: str) -> str:
    body = urllib.parse.urlencode({"content": text}).encode()
    req = urllib.request.Request(MCLOGS_API, data=body, headers={"User-Agent": core.UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        j = json.loads(r.read())
    if not j.get("success"):
        raise IOError(j.get("error", "mclo.gs upload failed"))
    return j["url"]


def diagnose(texts: list[str]) -> str:
    joined = "\n".join(t[-400_000:] for t in texts)
    for rx, hint in HINTS:
        if rx.search(joined):
            return hint
    return "Причина пока не ясна — отчёт отправлен владельцу сервера."


def report(nick: str, code: int, started_at: float, pack_version: str, error: str = "") -> dict:
    files = collect(started_at)
    links, texts = {}, []
    for key in ("crash-report", "jvm-crash", "latest.log", "debug.log", "portablemc.log", "launcher.log"):
        if key not in files:
            continue
        t = _read_tail(files[key])
        texts.append(t)
        try:
            links[key] = upload(t)
        except Exception as e:
            core.log.warning("upload %s failed: %s", key, e)
    hint = diagnose(texts) if not error else "Ошибка лаунчера: " + error[:300]
    summary = {"nick": nick, "exit_code": code, "pack": pack_version, "launcher": core.LAUNCHER_VERSION,
               "time": time.strftime("%Y-%m-%d %H:%M:%S"), "hint": hint, "links": links,
               "ram_gb": core.State().settings.get("ram"), "gpu": gpu_info(), "error": error}
    try:
        notify(summary)
        summary["sent"] = True
    except Exception as e:
        core.log.warning("crash notify failed: %s", e)
        summary["sent"] = False
    (core.ROOT / "logs" / "last-crash.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


def gpu_info() -> str:
    p = core.GAME / "logs" / "latest.log"
    try:
        m = re.search(r"Found graphics adapter: AdapterInfo\{vendor=(\w+), description='([^']+)'", p.read_text(encoding="utf-8", errors="replace")[:200000])
        return f"{m.group(1)} {m.group(2)}" if m else ""
    except Exception:
        return ""


def notify(summary: dict) -> None:
    """Deliver the report to the owner. Channel is configured in aero/report_channel.py (not in git)."""
    try:
        from . import report_channel
    except ImportError:
        raise RuntimeError("report channel not configured")
    report_channel.send(summary)
