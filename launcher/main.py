import os
import subprocess
import sys


def _rollback_if_broken(exc):
    """A broken self-update must not brick the launcher: swap back to the previous exe and restart it."""
    exe = sys.executable if getattr(sys, "frozen", False) else None
    if not exe or not os.path.exists(exe + ".old") or "--rolled-back" in sys.argv:
        raise exc
    os.replace(exe, exe + ".broken")
    os.replace(exe + ".old", exe)
    subprocess.Popen([exe, "--rolled-back"], close_fds=True, creationflags=0x00000008)
    sys.exit(0)


try:
    from aero import core, crash, remote  # noqa: F401  (import everything up front: catches broken builds)
    import truststore, certifi  # noqa: F401
    from aero.app import main, cli
except Exception as e:  # noqa: BLE001
    if "--selftest" in sys.argv:
        sys.exit(3)
    _rollback_if_broken(e)

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        try:   # the built exe must also reach the pack over HTTPS (TLS stack, certifi data bundled)
            core.http_get(core.INDEX_URL, timeout=30)
        except Exception:
            sys.exit(4)
        sys.exit(0)
    cli() if "--cli" in sys.argv else main()
