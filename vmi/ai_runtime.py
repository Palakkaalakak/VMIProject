"""Built-in local AI: no Ollama or LM Studio to install.

On the owner's request (AI Settings > Download) this fetches, into data/ai/:
  * the llama.cpp `llama-server` build for Windows + NVIDIA (newest CUDA 12/13 build; Vulkan as the fallback) and, for CUDA, its runtime zip
  * one GGUF model file (Gemma 4 12B, about 7 GB, from Hugging Face)
Downloads resume if interrupted. The server is started only when an opinion is asked for (all layers on the GPU) and stopped after
`IDLE_SECONDS` without use. Nothing is sent anywhere except these downloads; prompts stay on this PC.

NOT verifiable in the cloud container (no GPU, no Windows): the asset choice, the download and the resume are tested with fakes only.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from contextlib import contextmanager

from vmi import ai_settings
from vmi.config import get_settings

log = logging.getLogger("vmi.ai")

RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10"
# Gemma 4 12B, Google's own quantisation-aware 4-bit build: won the 2026-11-20 blind moat benchmark against Qwen3-14B and
# gpt-oss-20b on over-calls (the error the owner cares about most). Apache 2.0.
MODEL_FILE = "models/gemma-4-12b-it-qat-q4_0.gguf"
MODEL_URL = "https://huggingface.co/google/gemma-4-12B-it-qat-q4_0-gguf/resolve/main/gemma-4-12b-it-qat-q4_0.gguf"
MODEL_MIN_BYTES = 6_500_000_000                       # a finished file is about 7 GB; anything smaller is a partial download
SERVER_EXTRA = ["-fa", "on", "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",       # 8-bit KV cache: half the memory, negligible loss
                "--spec-type", "ngram-simple", "--spec-ngram-simple-size-n", "6", "--spec-ngram-simple-size-m", "32"]   # lossless speed-up: reuses prompt text
CHAT_KWARGS = {"enable_thinking": False}                                           # Gemma's thinking mode used up whole budgets
IDLE_SECONDS = 600
# ---- safeguards (a run once froze the PC and BitLocker locked it): the server is stopped, not left to grind, when the machine is stressed
MAX_RUN_SECONDS = int(os.environ.get("VMI_AI_MAX_RUN_SECONDS", 40 * 60))     # hard ceiling on one server's life, busy or not
MAX_GPU_TEMP_C = int(os.environ.get("VMI_AI_MAX_TEMP", 85))                  # stop at this GPU temperature; no start when already near it
MIN_START_RAM_MB = 2560                                                      # no start unless this much RAM is free (6 GB when layers are offloaded to RAM)
MIN_FREE_VRAM_MB = 400                                                       # stop when the GPU has less than this left (the display needs some)
GUARD_INTERVAL_SECONDS = 1                                                  # fresh readings, no timed restart lockout

DOWNLOAD: dict = {"running": False, "what": "", "done": 0, "total": 0, "error": ""}
_server: dict = {"proc": None, "port": None, "last_used": 0.0, "started": 0.0, "tripped": "", "tripped_at": 0.0, "active": 0}
_lock = threading.RLock()


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
        releases = json.loads(r.read())
    # GitHub's "latest" can point at a tag with no binaries (v1.0.0 did), so take the newest release that has a Windows build.
    picked = next((p for p in map(pick_assets, releases) if p), None)
    if picked is None:
        raise RuntimeError("no Windows llama.cpp build found in the recent releases (install Ollama instead)")
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
            model_path().parent.mkdir(parents=True, exist_ok=True)
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


CTX = 20480                      # the deep moat prompt is ~8.6k tokens + notes + answer
MODEL_LAYERS = 49                 # Gemma 4 12B: 48 blocks + output layer
MB_PER_LAYER = 145                # ~7 GB of weights over 49 layers
CHARS_PER_TOKEN = 3.3            # cautious (English prose is nearer 4): used to fit prompts inside CTX
KV_AND_BUFFERS_MB = 3000          # KV cache for CTX tokens (about 2 GB) + compute buffers + desktop headroom


def gpu_layers(free_mb: float | None = None) -> int:
    """How many layers to put on the GPU; the rest run from normal RAM (slower, but it works on smaller cards).
    99 = everything. 0 = CPU only (no NVIDIA GPU found). Override with the VMI_AI_GPU_LAYERS environment variable."""
    env = os.environ.get("VMI_AI_GPU_LAYERS", "").strip()
    if env.lstrip("-").isdigit():
        return int(env)
    if free_mb is None:
        try:
            out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                 timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0).stdout
            free_mb = max(float(x) for x in out.split())
        except Exception:
            return 0
    n = int((free_mb - KV_AND_BUFFERS_MB) // MB_PER_LAYER)
    return 99 if n >= MODEL_LAYERS else max(0, n)


def free_ram_mb() -> float | None:
    """Free physical memory in MB (None if unknown)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MS(ctypes.Structure):
                _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tp", ctypes.c_ulonglong), ("ap", ctypes.c_ulonglong),
                            ("tv", ctypes.c_ulonglong), ("av", ctypes.c_ulonglong), ("tx", ctypes.c_ulonglong), ("ax", ctypes.c_ulonglong),
                            ("ae", ctypes.c_ulonglong)]
            m = MS()
            m.l = ctypes.sizeof(MS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ap / 1048576
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) / 1024
    except Exception:
        pass
    return None


def gpu_state() -> dict | None:
    """{temp, free_mb} of the hottest / fullest GPU from nvidia-smi, or None when there is none."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,memory.free", "--format=csv,noheader,nounits"], capture_output=True,
                             text=True, timeout=2, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0).stdout
        rows = [[float(x) for x in ln.split(",")] for ln in out.strip().splitlines() if ln.strip()]
        return {"temp": max(r[0] for r in rows), "free_mb": min(r[1] for r in rows)} if rows else None
    except Exception:
        return None


class SafetyBlocked(RuntimeError):
    """Resource checks refused or stopped the built-in model."""


def _danger(limits: ai_settings.AISettings, *, reading: tuple | None = None) -> str:
    """Why the machine is too stressed for the AI right now ('' = fine)."""
    ram, gpu = (free_ram_mb(), gpu_state()) if reading is None else reading
    if gpu and gpu["temp"] >= min(MAX_GPU_TEMP_C, limits.max_gpu_temp_c):
        return f"the GPU reached {gpu['temp']:.0f} °C"
    if gpu and gpu["free_mb"] < MIN_FREE_VRAM_MB:
        return f"only {gpu['free_mb']:.0f} MB of GPU memory is left"
    if not limits.override_ram_guard and ram is not None and ram < limits.min_free_ram_mb:
        return f"free system RAM is down to {ram:.0f} MB (minimum {limits.min_free_ram_mb} MB)"
    return ""


@contextmanager
def active_request():
    """Idle timeout must not stop the server during an in-flight answer or tool lookup."""
    with _lock:
        _server["active"] += 1
    try:
        yield
    finally:
        with _lock:
            _server["active"] -= 1
            _server["last_used"] = time.time()


def _pidfile() -> Path:
    return ai_dir() / "llama-server.pid"


def kill_stale() -> None:
    """A llama-server left behind by an earlier crash or kill of this app is stopped (only the one recorded in our pid file)."""
    try:
        pid = int(_pidfile().read_text().strip())
        _pidfile().unlink(missing_ok=True)
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout
            if "llama-server" in out.lower():
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def _guard(proc: subprocess.Popen) -> None:
    """Stop the same server we inspected, never a replacement process."""
    while True:
        time.sleep(GUARD_INTERVAL_SECONDS)
        with _lock:
            if _server["proc"] is not proc or proc.poll() is not None:
                return
        limits = ai_settings.load()
        danger = _danger(limits)
        with _lock:
            if _server["proc"] is not proc or proc.poll() is not None:
                return
            max_seconds = min(MAX_RUN_SECONDS, limits.max_run_minutes * 60)
            why = (f"it reached the {max_seconds // 60}-minute safety limit"
                   if time.time() - _server["started"] >= max_seconds else danger)
            if why:
                _server["tripped"], _server["tripped_at"] = why, time.time()
                stop()
                return


def ensure_running(wait: float = 120.0) -> str:
    """Base URL of the built-in server, starting it when needed."""
    with _lock:
        if _server["proc"] is not None and _server["proc"].poll() is None:
            _server["last_used"] = time.time()
            return f"http://127.0.0.1:{_server['port']}"
        if not ready():
            raise RuntimeError("the built-in AI is not downloaded yet (AI Settings)")
        limits = ai_settings.load()
        why = _danger(limits)
        if why:
            raise SafetyBlocked(f"Cannot start the built-in AI: {why}. Retry as soon as readings recover.")
        kill_stale()
        first = gpu_layers()
        # start-up that dies (not enough GPU memory) is retried with fewer layers on the GPU; the rest then runs from normal RAM
        plan = [first] + ([max(0, min(first, MODEL_LAYERS) - 8), 0] if first > 0 else [])
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        for ngl in dict.fromkeys(plan):
            ram = free_ram_mb()
            need = max(limits.min_free_ram_mb, MIN_START_RAM_MB if ngl >= 99 else 6144)
            if not limits.override_ram_guard and ram is not None and ram < need:
                raise SafetyBlocked(f"Cannot load the built-in model with {ram:.0f} MB of free system RAM. "
                                    f"This configuration needs {need} MB to start. Close other programs, or review the RAM override in AI Settings.")
            port = _free_port()
            cmd = [str(server_exe()), "-m", str(model_path()), "--port", str(port), "--host", "127.0.0.1", "-ngl", str(ngl), "-c", str(CTX), "--jinja", "-t", str(max(2, (os.cpu_count() or 4) // 2))] + SERVER_EXTRA
            low = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)       # the desktop stays responsive
            _server["proc"] = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags | low)
            _server["run_trip_from"] = _server["tripped_at"]
            _server["port"], _server["last_used"], _server["started"] = port, time.time(), time.time()
            try:
                _pidfile().write_text(str(_server["proc"].pid))
            except OSError:
                pass
            proc = _server["proc"]
            deadline = time.time() + wait
            died = False
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                        if r.status == 200:
                            threading.Thread(target=_idle_watch, args=(proc,), daemon=True).start()
                            threading.Thread(target=_guard, args=(proc,), daemon=True, name="vmi-ai-guard").start()
                            return f"http://127.0.0.1:{port}"
                except Exception:
                    if _server["proc"].poll() is not None:
                        died = True
                        break
                    time.sleep(1.5)
            if not died:
                stop()
                raise RuntimeError("the AI server did not become ready in time")
        raise RuntimeError("the AI server exited at start-up even on the CPU (driver or memory problem?)")


def _idle_watch(proc: subprocess.Popen) -> None:
    while True:
        time.sleep(30)
        with _lock:
            if _server["proc"] is not proc or proc.poll() is not None:
                return
            if not _server["active"] and time.time() - _server["last_used"] > IDLE_SECONDS:
                stop()
                return


def stop() -> None:
    with _lock:
        p = _server["proc"]
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        _server["proc"] = None
        try:
            _pidfile().unlink(missing_ok=True)
        except OSError:
            pass

import atexit  # noqa: E402
atexit.register(stop)          # the server never outlives the app


def room(output_tokens: int, used_chars: int = 0) -> int:
    """Characters of source text that still fit in CTX beside `used_chars` of prompt and an `output_tokens` answer."""
    return max(0, int((CTX - output_tokens - 400) * CHARS_PER_TOKEN) - used_chars)


def squeeze(text: str, limit: int) -> str:
    """Cut `text` to `limit` characters by trimming its longest blocks, so late blocks are not simply lost."""
    if len(text) <= limit:
        return text
    blocks = text.split("\n\n")
    lo, hi = 0, max(map(len, blocks))
    while lo < hi:
        mid = (lo + hi + 1) // 2
        lo, hi = (mid, hi) if sum(min(len(b), mid) + 2 for b in blocks) <= limit else (lo, mid - 1)
    return "\n\n".join(b[:lo] for b in blocks)[:limit]


def chat(prompt: str, timeout: float = 300.0) -> str:
    """One answer from the built-in server (OpenAI-style chat endpoint)."""
    base = ensure_running()
    body = json.dumps({"messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 700,
                       "chat_template_kwargs": CHAT_KWARGS}).encode()
    req = urllib.request.Request(f"{base}/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = json.loads(r.read())["choices"][0]["message"]["content"]
    _server["last_used"] = time.time()
    return text.split("</think>")[-1].strip()


def _post_chat(base: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(f"{base}/v1/chat/completions", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        choice = json.loads(r.read())["choices"][0]
        return {**choice["message"], "finish_reason": choice.get("finish_reason")}


def chat_with_tools(messages: list[dict], tools: list[dict], run_tool, max_rounds: int = 5, timeout: float = 300.0,
                    max_tokens: int = 900, on_tool=None, require_first_tool: bool = False, think: bool = False,
                    base_url: str | None = None, keep_chars: int = 24000) -> str:
    """Chat loop: the model may call `tools` (OpenAI-style) up to `max_rounds` times; `run_tool(name, args) -> str` answers them.
    The last round is sent without tools so the model must write its answer."""
    base = base_url or ensure_running()
    messages = list(messages)
    for rnd in range(max_rounds + 1):
        # keep the conversation inside the context window: older tool results shrink to a stub, the last 4 stay whole
        tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if sum(len(str(m.get("content", ""))) for m in messages) > keep_chars:
            for i in tool_idx[:-4]:
                messages[i] = {**messages[i], "content": "[older result trimmed; rely on what you noted from it]"}
        body = {"messages": messages, "temperature": 0.3, "max_tokens": max_tokens, "chat_template_kwargs": {**CHAT_KWARGS, "enable_thinking": think}}
        if rnd < max_rounds:
            body["tools"] = tools
            if rnd == 0 and require_first_tool:
                body["tool_choice"] = "required"          # research before the first word of the answer
        try:
            msg = _post_chat(base, body, timeout)
        except urllib.error.HTTPError:
            # usually the conversation outgrew the context window: shrink every older tool result hard and retry once
            tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
            for i in tool_idx[:-1]:
                messages[i] = {**messages[i], "content": "[older result trimmed]"}
            if tool_idx:
                last = messages[tool_idx[-1]]
                messages[tool_idx[-1]] = {**last, "content": str(last.get("content", ""))[:1500]}
            body["messages"] = messages
            msg = _post_chat(base, body, timeout)
        if not base_url:
            _server["last_used"] = time.time()
        calls = msg.get("tool_calls") or []
        if not calls:
            return (msg.get("content") or "").split("</think>")[-1].strip()
        messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            fn = c.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {}
            if on_tool:
                on_tool(fn.get("name", ""), args)
            messages.append({"role": "tool", "tool_call_id": c.get("id", ""), "content": str(run_tool(fn.get("name", ""), args))[:3000]})
    return ""


def status() -> dict:
    return {"server_present": server_exe() is not None, "model_present": model_present(), "ready": ready(),
            "running": _server["proc"] is not None and _server["proc"].poll() is None,
            "download": dict(DOWNLOAD), "model": MODEL_FILE, "supported": sys.platform == "win32",
            "safety_stop": _server["tripped"]}
