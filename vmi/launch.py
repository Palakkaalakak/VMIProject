"""One-click launcher: `python -m vmi.launch` (called by `Start VMI.bat`).

  1. installs the dependencies once (and again only when requirements.txt changes)
  2. if the app already answers on the port, just opens the browser
  3. otherwise starts the server, waits until it is ready, opens http://localhost:PORT and stays in the foreground
     showing the server log; Ctrl+C or closing the window stops it.

Options: --no-browser, --no-install, --port N
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import time
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WAIT_SECS = 60


def say(msg: str) -> None:
    print(f"[VMI] {msg}", flush=True)


# --------------------------------------------------------------------------------------------- dependencies
def deps_hash(root: Path = ROOT) -> str:
    return hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()


def ensure_deps(root: Path = ROOT, run=subprocess.call) -> bool:
    """Install requirements once; returns True when something was installed (or nothing was needed)."""
    marker = root / "data" / ".deps-hash"
    want = deps_hash(root)
    if marker.exists() and marker.read_text().strip() == want:
        return True
    say("Installing the required packages (one time only, a few minutes)...")
    code = run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-r",
                str(root / "requirements.txt")])
    if code != 0:
        say("Installing failed (see the messages above). Check the internet connection and run this again.")
        return False
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(want)
    return True


# ------------------------------------------------------------------------------------------------- server
def is_up(port: int, timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def wait_until_up(port: int, proc, secs: float = WAIT_SECS, sleep=time.sleep) -> bool:
    deadline = time.monotonic() + secs
    while time.monotonic() < deadline:
        if is_up(port):
            return True
        if proc.poll() is not None:
            return False
        sleep(0.5)
    return False


def serve(port: int, open_browser: bool = True, root: Path = ROOT) -> int:
    if is_up(port):
        say(f"The app is already running: opening http://localhost:{port}")
        if open_browser:
            webbrowser.open(f"http://localhost:{port}")
        return 0
    log_path = root / "data" / "launcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "uvicorn", "vmi.api.app:app", "--host", "127.0.0.1", "--port", str(port)]
    say("Starting the app...")
    import signal
    import threading

    signal.signal(signal.SIGTERM, lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()))   # same clean stop as Ctrl+C
    proc = subprocess.Popen(cmd, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail: deque[str] = deque(maxlen=25)

    def pump() -> None:
        with open(log_path, "a", encoding="utf-8") as log:
            for line in proc.stdout:               # type: ignore[union-attr]
                print(line, end="", flush=True)
                log.write(line)
                tail.append(line)

    threading.Thread(target=pump, daemon=True).start()
    try:
        if not wait_until_up(port, proc):
            say(f"The app did not start. Last messages:\n{''.join(tail)}")
            return 1
        say(f"Ready: http://localhost:{port}   (close this window or press Ctrl+C to stop the app)")
        if open_browser:
            webbrowser.open(f"http://localhost:{port}")
        return proc.wait()
    except KeyboardInterrupt:
        say("Stopping...")
        return 0
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-install", action="store_true")
    a = ap.parse_args(argv)
    if sys.version_info < (3, 11):
        say(f"Python 3.11 or newer is needed (this is {sys.version.split()[0]}).")
        return 1
    if not a.no_install and not ensure_deps():
        return 1
    port = a.port
    if port is None:
        from vmi.config import get_settings
        port = get_settings().port
    return serve(port, open_browser=not a.no_browser)


if __name__ == "__main__":
    sys.exit(main())
