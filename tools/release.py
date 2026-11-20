"""Release a new launcher version: bump, build, GitHub release, manifest, push.

Usage (from repo root): python -I tools/release.py 1.0.5 "Что изменилось"
Edits files as UTF-8 bytes only (PowerShell Get-Content once re-read core.py as cp1251 and broke all Russian text).
"""
import hashlib, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GH = r"C:\Program Files\GitHub CLI\gh.exe"
REF_ZIP = ROOT.parent / "Aero-Arcana (client).zip"


def run(*cmd, **kw):
    print(">", " ".join(map(str, cmd)))
    subprocess.run(cmd, check=True, **kw)


def main(version, notes):
    core = ROOT / "launcher" / "aero" / "core.py"
    text = core.read_bytes().decode("utf-8")
    text, n = re.subn(r'LAUNCHER_VERSION = "[^"]+"', f'LAUNCHER_VERSION = "{version}"', text)
    assert n == 1
    assert "Скачивание сборки" in text, "core.py Russian text looks broken"
    core.write_bytes(text.encode("utf-8"))
    venv_py = ROOT / "launcher" / ".venv" / "Scripts" / "python.exe"
    # 1) every module must compile and import (PyInstaller silently drops modules with syntax errors)
    run(str(venv_py), "-c", "import py_compile, glob; [py_compile.compile(f, doraise=True) for f in glob.glob('aero/*.py') + ['main.py']]; "
        "import aero.core, aero.app, aero.crash, aero.remote, truststore, certifi; print('modules ok')", cwd=ROOT / "launcher")
    run("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "launcher" / "build.ps1"))
    exe = ROOT / "launcher" / "dist" / "AeroArcana.exe"
    # 2) the built exe must start and import itself
    rc = subprocess.run([str(exe), "--selftest"], timeout=120).returncode
    assert rc == 0, f"built exe failed self-test (exit {rc}) — not releasing"
    print("exe self-test ok")
    run(GH, "release", "create", f"v{version}", str(exe), "-R", "Nikogrelis/aero-arcana",
        "--title", f"Aero Arcana Launcher {version}", "--notes", notes, "--latest")
    run(sys.executable, "-I", str(ROOT / "tools" / "build_manifest.py"), str(REF_ZIP))
    idx = (ROOT / "pack" / "index.json").read_text(encoding="utf-8")
    assert hashlib.sha256(exe.read_bytes()).hexdigest() in idx
    run("git", "-C", str(ROOT), "add", "-A")
    run("git", "-C", str(ROOT), "-c", "user.name=Nikogrelis", "-c", "user.email=Nikogrelis@users.noreply.github.com",
        "commit", "-q", "-m", f"Launcher {version}: {notes}")
    run("git", "-C", str(ROOT), "push", "-q", "origin", "main")
    print("released", version)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
