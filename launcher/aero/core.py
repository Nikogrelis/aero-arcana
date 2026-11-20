"""Aero Arcana launcher core: pack sync, Minecraft/NeoForge install (portablemc) and game start.

Layout (all under ROOT = %APPDATA%\\.aeroarcana, or AERO_ROOT for tests):
  ROOT/                 portablemc main dir: versions, libraries, assets, Java runtimes
  ROOT/game/            the game directory: mods, config, saves, options
  ROOT/launcher.json    settings + hashes of the files the launcher installed
  ROOT/logs/launcher.log
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import logging
import os
import pathlib
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

INDEX_URL = "https://raw.githubusercontent.com/Nikogrelis/aero-arcana/main/pack/index.json"
NEWS_URL = "https://raw.githubusercontent.com/Nikogrelis/aero-arcana/main/pack/NEWS.md"
RELEASE_API = "https://api.github.com/repos/Nikogrelis/aero-arcana/releases/latest"
UA = "AeroArcanaLauncher/1.0 (+https://github.com/Nikogrelis/aero-arcana)"
LAUNCHER_VERSION = "1.0.6"

ROOT = pathlib.Path(os.environ.get("AERO_ROOT") or pathlib.Path(os.environ["APPDATA"]) / ".aeroarcana")
GAME = ROOT / "game"
STATE_FILE = ROOT / "launcher.json"
NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "logs").mkdir(exist_ok=True)
log = logging.getLogger("aero")
if not log.handlers:
    h = logging.FileHandler(ROOT / "logs" / "launcher.log", encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)
    log.setLevel(logging.INFO)


# ---------------------------------------------------------------- helpers
def resource(name: str) -> pathlib.Path:
    """File bundled next to the code (or inside the PyInstaller bundle)."""
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).resolve().parent.parent))
    return base / name


def offline_uuid(nick: str) -> str:
    """Same UUID as a server in offline mode gives this nick (case-sensitive)."""
    h = bytearray(hashlib.md5(("OfflinePlayer:" + nick).encode()).digest())
    h[6] = h[6] & 0x0F | 0x30
    h[8] = h[8] & 0x3F | 0x80
    return str(uuid.UUID(bytes=bytes(h)))


def total_ram_gb() -> float:
    try:
        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                        ("avail", ctypes.c_ulonglong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                        ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("ae", ctypes.c_ulonglong)]
        m = MS(); m.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.total / 1024 ** 3
    except Exception:
        return 16.0


def default_ram() -> int:
    t = total_ram_gb()
    return int(max(6, min(10, t * 0.5)))


def http_get(url: str, timeout=60) -> bytes:
    req = urllib.request.Request(urllib.parse.quote(url, safe=":/%?=&"), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sha1_file(p: pathlib.Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_safe_rel(rel: str) -> bool:
    p = pathlib.PurePosixPath(rel)
    return not p.is_absolute() and ".." not in p.parts and rel and not rel.startswith(("/", "\\"))


# ---------------------------------------------------------------- state
class State:
    def __init__(self):
        try:
            self.data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}
        self.data.setdefault("settings", {})
        self.data.setdefault("files", {})   # rel path -> {"sha1", "size", "mtime"}
        self.lock = threading.Lock()

    @property
    def settings(self):
        return self.data["settings"]

    def save(self):
        with self.lock:
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(STATE_FILE)

    def local_sha1(self, rel: str) -> str | None:
        """sha1 of the file on disk, using the cached value when size+mtime did not change."""
        p = GAME / rel
        if not p.exists():
            return None
        st = p.stat()
        rec = self.data["files"].get(rel)
        if rec and rec.get("size") == st.st_size and abs(rec.get("mtime", 0) - st.st_mtime) < 1e-3:
            return rec["sha1"]
        return sha1_file(p)

    def remember(self, rel: str):
        p = GAME / rel
        st = p.stat()
        with self.lock:
            self.data["files"][rel] = {"sha1": sha1_file(p), "size": st.st_size, "mtime": st.st_mtime}


# ---------------------------------------------------------------- pack sync
def fetch_index(state: State) -> dict:
    cache = ROOT / "index.cache.json"
    try:
        data = http_get(INDEX_URL + f"?t={int(time.time())}", timeout=30)
        idx = json.loads(data)
        cache.write_bytes(data)
        return idx
    except Exception as e:
        log.warning("index download failed: %s", e)
        if cache.exists():
            return json.loads(cache.read_bytes())
        raise RuntimeError("Нет связи с сервером обновлений (GitHub). Проверьте интернет.") from e


def plan_sync(idx: dict, state: State) -> tuple[list, list]:
    """Return (files to download, mods to delete)."""
    todo = []
    for f in idx["files"]:
        rel = f["path"]
        if not is_safe_rel(rel):
            continue
        cur = state.local_sha1(rel)
        installed = state.data["files"].get(rel, {}).get("sha1")
        pol = f.get("policy", "force")
        if cur == f["sha1"]:
            continue
        if cur is None:
            if pol == "once" and installed:
                continue          # player deleted a preference file on purpose
            todo.append(f)
        elif pol == "force":
            todo.append(f)
        elif pol == "keep-modified" and installed and cur == installed:
            todo.append(f)        # untouched by the player -> safe to update
        # 'once' or player-modified 'keep-modified' -> leave as is
    wanted = {f["path"] for f in idx["files"] if f["path"].startswith("mods/")}
    mods_dir = GAME / "mods"
    stale = [p for p in mods_dir.glob("*.jar") if f"mods/{p.name}" not in wanted] if mods_dir.exists() else []
    return todo, stale


def download_files(todo: list, state: State, progress) -> None:
    total = sum(f["size"] for f in todo) or 1
    done = [0]
    lock = threading.Lock()

    def one(f):
        rel = f["path"]
        dst = GAME / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".part")
        last_err = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(urllib.parse.quote(f["url"], safe=":/%?=&"), headers={"User-Agent": UA})
                h = hashlib.sha1()
                with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:
                    while True:
                        chunk = r.read(1 << 16)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        with lock:
                            done[0] += len(chunk)
                if h.hexdigest() != f["sha1"]:
                    raise IOError("checksum mismatch")
                tmp.replace(dst)
                state.remember(rel)
                return
            except Exception as e:
                last_err = e
                log.warning("download %s attempt %d: %s", rel, attempt + 1, e)
                time.sleep(1 + attempt * 2)
        raise RuntimeError(f"Не удалось скачать {rel}: {last_err}")

    stop = threading.Event()

    def ticker():
        while not stop.wait(0.25):
            progress("sync", min(done[0] / total, 1.0), f"Скачивание сборки: {done[0] / 2**20:.0f} / {total / 2**20:.0f} МБ")
    t = threading.Thread(target=ticker, daemon=True)
    t.start()
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for fut in as_completed([ex.submit(one, f) for f in todo]):
                fut.result()
    finally:
        stop.set()
        state.save()


def ensure_servers_dat(server: dict) -> None:
    """Add the pack server to the multiplayer list if servers.dat does not exist yet."""
    p = GAME / "servers.dat"
    if p.exists():
        return

    def s(tag_name, value):
        n, v = tag_name.encode(), value.encode()
        return b"\x08" + struct.pack(">H", len(n)) + n + struct.pack(">H", len(v)) + v
    entry = s("name", server["name"]) + s("ip", f'{server["host"]}:{server["port"]}') + b"\x00"
    body = b"\x09" + struct.pack(">H", 7) + b"servers" + b"\x0a" + struct.pack(">i", 1) + entry + b"\x00"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x0a\x00\x00" + body)


def sync_pack(state: State, progress) -> dict:
    progress("check", 0.0, "Проверка обновлений…")
    idx = fetch_index(state)
    progress("check", 0.0, "Сверка файлов сборки…")
    todo, stale = plan_sync(idx, state)
    for p in stale:
        log.info("remove stale mod %s", p.name)
        p.unlink(missing_ok=True)
        state.data["files"].pop(f"mods/{p.name}", None)
    if todo:
        log.info("download %d files (%.1f MB)", len(todo), sum(f["size"] for f in todo) / 2**20)
        download_files(todo, state, progress)
    ensure_servers_dat(idx["server"])
    state.data["pack_version"] = idx["version"]
    state.save()
    progress("sync", 1.0, "Сборка актуальна")
    return idx


# ---------------------------------------------------------------- game install + launch
PMC_URL = "https://github.com/theorzr/portablemc/releases/download/v5.0.6/portablemc-5.0.6-windows-x86_64-msvc.zip"
PMC_SHA256 = "e693a0d05bbf87411ae5c0967e04c2f461ec2005cbbdf6536e4195ff3fafac89"


def portablemc_exe(progress=None) -> pathlib.Path:
    """PortableMC (Apache-2.0) is not bundled: downloaded once, pinned by SHA-256."""
    exe = ROOT / "tools" / "portablemc-5.0.6" / "portablemc.exe"
    if exe.exists():
        return exe
    if progress:
        progress("install", None, "Загрузка установщика Minecraft…")
    data = http_get(PMC_URL, timeout=120)
    if hashlib.sha256(data).hexdigest() != PMC_SHA256:
        raise RuntimeError("Установщик Minecraft скачался повреждённым, попробуйте ещё раз.")
    import io, zipfile
    exe.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in ("portablemc.exe", "LICENSE"):
            (exe.parent / name).write_bytes(z.read(name))
    return exe


def start_game(idx: dict, nick: str, ram_gb: int, progress, on_started, join_server: bool) -> int:
    """Install (if needed) and start the game. Blocks until the game exits; returns exit code."""
    version = f"neoforge::{idx['neoforge']}"
    jvm_args = [f"-Xmx{ram_gb}G", f"-Xms{min(ram_gb, 4)}G", "-XX:+UseG1GC", "-XX:+UnlockExperimentalVMOptions",
                "-XX:G1NewSizePercent=20", "-XX:G1ReservePercent=20", "-XX:MaxGCPauseMillis=50"]
    cmd = [str(portablemc_exe(progress)), "--main-dir", str(ROOT), "--output", "machine", "start",
           "--mc-dir", str(GAME), "--jvm-policy", "mojang-then-system",
           "-u", nick, "-i", offline_uuid(nick), "--jvm-arg=" + ",".join(jvm_args), version]
    if join_server:
        cmd[cmd.index(version):cmd.index(version)] = ["--join-server", idx["server"]["host"],
                                                       "--join-server-port", str(idx["server"]["port"])]
    log.info("run %s", " ".join(cmd))
    GAME.mkdir(parents=True, exist_ok=True)
    progress("install", 0.0, "Подготовка Minecraft и NeoForge…")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT,
                            creationflags=NO_WINDOW, text=True, encoding="utf-8", errors="replace")
    game_log = open(ROOT / "logs" / "portablemc.log", "w", encoding="utf-8")
    started = False
    errors = []
    for line in proc.stdout:
        game_log.write(line)
        parts = line.rstrip("\n").split("\t")
        kind = parts[0]
        # machine output: "download\t<n>/<count>\t<bytes>/<total>\t<seconds>\t<speed>", "neoforge_installing", ...
        if kind == "download" and len(parts) >= 3 and "/" in parts[2]:
            try:
                cur, tot = (float(x) for x in parts[2].split("/"))
                progress("install", cur / tot if tot else 0, f"Установка Minecraft: {cur / 2**20:.0f} / {tot / 2**20:.0f} МБ")
            except ValueError:
                pass
        elif kind.startswith("neoforge_"):
            progress("install", None, "Установка NeoForge… (только в первый раз, 1–3 минуты)")
        elif kind in ("load_jvm", "loaded_jvm"):
            progress("install", None, "Подготовка Java…")
        elif kind in ("assets_loading", "verified_assets", "load_libraries"):
            progress("install", None, "Проверка файлов игры…")
        elif kind.startswith("error_"):
            errors.append(line.strip())
        if not started and (kind in ("launched", "game_launched", "launch") or kind.startswith("game_")):
            started = True
            progress("install", 1.0, "Запуск игры…")
            on_started()
    code = proc.wait()
    game_log.close()
    if not started and code != 0:
        raise RuntimeError("Не удалось установить или запустить игру:\n" + ("\n".join(errors[-5:]) or f"код {code}")
                           + f"\nПодробности: {ROOT / 'logs' / 'portablemc.log'}")
    return code


# ---------------------------------------------------------------- misc
def server_status(host: str, port: int, timeout=4.0) -> dict:
    """Minecraft Server List Ping (1.7+)."""
    def varint(n):
        out = b""
        while True:
            b = n & 0x7F
            n >>= 7
            out += bytes([b | (0x80 if n else 0)])
            if not n:
                return out

    def read_varint(sock):
        n = shift = 0
        while True:
            b = sock.recv(1)
            if not b:
                raise IOError("closed")
            n |= (b[0] & 0x7F) << shift
            shift += 7
            if not b[0] & 0x80:
                return n
    try:
        t0 = time.time()
        with socket.create_connection((host, port), timeout=timeout) as s:
            hb = host.encode()
            hs = varint(0) + varint(767) + varint(len(hb)) + hb + struct.pack(">H", port) + varint(1)
            s.sendall(varint(len(hs)) + hs + varint(1) + varint(0))
            read_varint(s); read_varint(s)
            ln = read_varint(s)
            data = b""
            while len(data) < ln:
                chunk = s.recv(ln - len(data))
                if not chunk:
                    break
                data += chunk
        j = json.loads(data.decode("utf-8", "replace"))
        players = j.get("players", {})
        names = [p.get("name") for p in players.get("sample", []) or []]
        return {"online": True, "players": players.get("online", 0), "max": players.get("max", 0),
                "names": names, "ping": int((time.time() - t0) * 1000)}
    except Exception as e:
        return {"online": False, "error": str(e)}


def launcher_update() -> dict | None:
    """Newer launcher release on GitHub (tag vX.Y.Z), if any."""
    try:
        rel = json.loads(http_get(RELEASE_API, timeout=10))
        tag = rel.get("tag_name", "").lstrip("v")
        newer = tuple(int(x) for x in tag.split(".")) > tuple(int(x) for x in LAUNCHER_VERSION.split("."))
        return {"version": tag, "url": rel.get("html_url")} if newer else None
    except Exception:
        return None


def fetch_news() -> str:
    try:
        return http_get(NEWS_URL + f"?t={int(time.time())}", timeout=15).decode("utf-8")
    except Exception:
        return ""
