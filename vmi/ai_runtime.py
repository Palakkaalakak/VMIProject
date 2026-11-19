"""Built-in local AI: no Ollama or LM Studio to install.

On the owner's request (Settings > AI helper > Download) this fetches, into data/ai/:
  * the llama.cpp `llama-server` build for Windows + NVIDIA (newest CUDA 12/13 build; Vulkan as the fallback) and, for CUDA, its runtime zip
  * one GGUF model file (default Qwen3-14B Q4_K_M, about 9 GB, from Hugging Face)
Downloads resume if interrupted. The server is started only when an opinion is asked for (all layers on the GPU) and stopped after
`IDLE_SECONDS` without use. Nothing is sent anywhere except these downloads; prompts stay on this PC.

NOT verifiable in the cloud container (no GPU, no Windows): the asset choice, the download and the resume are tested with fakes only.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from vmi.config import get_settings

log = logging.getLogger("vmi.ai")

RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
MODEL_FILE = "Qwen3-14B-Q4_K_M.gguf"
MODEL_URL = f"https://huggingface.co/Qwen/Qwen3-14B-GGUF/resolve/main/{MODEL_FILE}"
MODEL_MIN_BYTES = 8_000_000_000                       # a finished file is about 9 GB; anything smaller is a partial download
IDLE_SECONDS = 600

DOWNLOAD: dict = {"running": False, "what": "", "done": 0, "total": 0, "error": ""}
_server: dict = {"proc": None, "port": None, "last_used": 0.0}
_lock = threading.Lock()


def ai_dir() -> Path:
    d = get_settings().data_dir / "ai"
    d.mkdir(parents=True, exist_ok=True)
    return d


def server_exe() -> Path | None:
    found = sorted(ai_dir().glob("**/llama-server.exe")) or sorted(ai_dir().glob("**/llama-server"))
    return found[0] if found else None


def model_path() -> Path:
    return ai_dir() / MODEL_FILE


def model_present() -> bool:
    p = model_path()
    return p.exists() and p.stat().st_size >= MODEL_MIN_BYTES


# ---------------------------------------------------------------------------------------------------- choosing the build
def pick_assets(release: dict) -> tuple[str, str | None] | None:
    """(server zip url, CUDA-runtime zip url or None) from a llama.cpp release: Windows x64, newest CUDA first, else Vulkan."""
    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
    cuda = []
    for name in assets:
        m = re.fullmatch(r"llama-.*-bin-win-cuda-(\d+)\.(\d+)-x64\.zip", name)
        if m:
            cuda.append(((int(m.group(1)), int(m.group(2))), name))
    if cuda:
        ver, name = max(cuda)
        rt = next((u for n, u in assets.items() if re.fullmatch(rf"cudart-llama-bin-win-cuda-{ver[0]}\.{ver[1]}-x64\.zip", n)), None)
        return assets[name], rt
    vk = next((u for n, u in assets.items() if re.fullmatch(r"llama-.*-bin-win-vulkan-x64\.zip", n)), None)
    return (vk, None) if vk else None


# ---------------------------------------------------------------------------------------------------- downloading
def _download(url: str, dest: Path, what: str, opener=urllib.request.urlopen) -> None:
    """Resumable download to `dest` (written as dest.part, renamed at the end)."""
    part = dest.with_suffix(dest.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    req = urllib.request.Request(url, headers={"User-Agent": "vmi-toolkit", **({"Range": f"bytes={have}-"} if have else {})})
    with opener(req, timeout=60) as r:
        resumed = getattr(r, "status", 200) == 206
        total = int(r.headers.get("Content-Length") or 0) + (have if resumed else 0)
        DOWNLOAD.update(what=what, done=have if resumed else 0, total=total)
        with open(part, "ab" if resumed else "wb") as out:
            while chunk := r.read(1 << 20):
                out.write(chunk)
                DOWNLOAD["done"] += len(chunk)
    part.replace(dest)


def _install_runtime() -> None:
    if server_exe() is not None:
        return
    with urllib.request.urlopen(urllib.request.Request(RELEASES_API, headers={"User-Agent": "vmi-toolkit"}), timeout=30) as r:
        picked = pick_assets(json.loads(r.read()))
    if picked is None:
        raise RuntimeError("no Windows llama.cpp build found in the latest release (install Ollama instead)")
    for url in [u for u in picked if u]:
        zp = ai_dir() / url.rsplit("/", 1)[-1]
        _download(url, zp, f"runtime {zp.name}")
        with zipfile.ZipFile(zp) as z:
            z.extractall(ai_dir() / "server")
        zp.unlink()


def _run_download() -> None:
    try:
        _install_runtime()
        if not model_present():
            _download(MODEL_URL, model_path(), MODEL_FILE)
        DOWNLOAD["error"] = ""
    except Exception as exc:
        DOWNLOAD["error"] = f"{type(exc).__name__}: {exc}"
        log.warning("AI download failed: %s", exc)
    finally:
        DOWNLOAD["running"] = False


def start_download() -> dict:
    """Begin (or resume) the downloads in the background."""
    with _lock:
        if not DOWNLOAD["running"]:
            DOWNLOAD.update(running=True, error="", done=0, total=0, what="starting")
            threading.Thread(target=_run_download, daemon=True, name="vmi-ai-download").start()
    return status()


def remove() -> None:
    stop()
    shutil.rmtree(ai_dir(), ignore_errors=True)


# ---------------------------------------------------------------------------------------------------- running the server
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ready() -> bool:
    return server_exe() is not None and model_present()


def ensure_running(wait: float = 120.0) -> str:
    """Base URL of the built-in server, starting it when needed."""
    with _lock:
        if _server["proc"] is not None and _server["proc"].poll() is None:
            _server["last_used"] = time.time()
            return f"http://127.0.0.1:{_server['port']}"
        if not ready():
            raise RuntimeError("the built-in AI is not downloaded yet (Settings > AI helper)")
        port = _free_port()
        cmd = [str(server_exe()), "-m", str(model_path()), "--port", str(port), "--host", "127.0.0.1", "-ngl", "99", "-c", "8192"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        _server["proc"] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        _server["port"], _server["last_used"] = port, time.time()
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    threading.Thread(target=_idle_watch, daemon=True).start()
                    return f"http://127.0.0.1:{port}"
        except Exception:
            if _server["proc"].poll() is not None:
                raise RuntimeError("the AI server exited at start-up (GPU memory or driver?)")
            time.sleep(1.5)
    stop()
    raise RuntimeError("the AI server did not become ready in time")


def _idle_watch() -> None:
    while _server["proc"] is not None and _server["proc"].poll() is None:
        time.sleep(30)
        if time.time() - _server["last_used"] > IDLE_SECONDS:
            stop()
            return


def stop() -> None:
    p = _server["proc"]
    if p is not None and p.poll() is None:
        p.terminate()
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
    _server["proc"] = None


def chat(prompt: str, timeout: float = 300.0) -> str:
    """One answer from the built-in server (OpenAI-style chat endpoint)."""
    base = ensure_running()
    body = json.dumps({"messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 700}).encode()
    req = urllib.request.Request(f"{base}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"]
    _server["last_used"] = time.time()
    return text.split("</think>")[-1].strip()


def status() -> dict:
    return {"server_present": server_exe() is not None, "model_present": model_present(), "ready": ready(),
            "running": _server["proc"] is not None and _server["proc"].poll() is None,
            "download": dict(DOWNLOAD), "model": MODEL_FILE, "supported": sys.platform == "win32"}
