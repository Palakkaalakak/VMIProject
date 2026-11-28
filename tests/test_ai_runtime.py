import io

from vmi import ai_runtime as R

REL = {"assets": [{"name": n, "browser_download_url": f"https://x/{n}"} for n in (
    "llama-b9000-bin-win-cuda-12.4-x64.zip", "llama-b9000-bin-win-cuda-13.1-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip",
    "cudart-llama-bin-win-cuda-13.1-x64.zip", "llama-b9000-bin-win-vulkan-x64.zip", "llama-b9000-bin-ubuntu-x64.zip")]}


def test_newest_cuda_build_and_its_runtime_are_picked():
    server, rt = R.pick_assets(REL)
    assert server.endswith("cuda-13.1-x64.zip") and rt.endswith("cudart-llama-bin-win-cuda-13.1-x64.zip")


def test_vulkan_is_the_fallback_and_nothing_found_is_none():
    only_vk = {"assets": [a for a in REL["assets"] if "vulkan" in a["name"]]}
    assert R.pick_assets(only_vk) == ("https://x/llama-b9000-bin-win-vulkan-x64.zip", None)
    assert R.pick_assets({"assets": [REL["assets"][-1]]}) is None


class _Resp(io.BytesIO):
    def __init__(self, data, status=200, total=None):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_download_resumes_a_partial_file(tmp_path):
    dest = tmp_path / "m.gguf"
    (tmp_path / "m.gguf.part").write_bytes(b"AAAA")
    seen = {}

    def opener(req, timeout=0):
        seen["range"] = req.headers.get("Range")
        return _Resp(b"BBBB", status=206)
    R._download("https://x/m", dest, "model", opener=opener)
    assert seen["range"] == "bytes=4-" and dest.read_bytes() == b"AAAABBBB" and not (tmp_path / "m.gguf.part").exists()


def test_status_reports_not_ready_before_any_download(tmp_path, monkeypatch):
    from vmi.config import get_settings
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    s = R.status()
    assert s["ready"] is False and s["server_present"] is False and s["model_present"] is False


def test_retry_after_one_second_uses_current_readings(tmp_path, monkeypatch):
    from vmi.ai_settings import AISettings
    import pytest

    class Proc:
        pid = 314
        def poll(self): return None

    monkeypatch.setattr(R, "_server", {"proc": None, "tripped": "hot", "tripped_at": 10.0})
    monkeypatch.setattr(R.time, "time", lambda: 11.0)
    monkeypatch.setattr(R, "ready", lambda: True)
    monkeypatch.setattr(R.ai_settings, "load", AISettings)
    monkeypatch.setattr(R, "free_ram_mb", lambda: 8192)
    temp = [85]
    monkeypatch.setattr(R, "gpu_state", lambda: {"temp": temp[0], "free_mb": 10000})
    monkeypatch.setattr(R, "kill_stale", lambda: None)
    monkeypatch.setattr(R, "gpu_layers", lambda: 99)
    monkeypatch.setattr(R, "_free_port", lambda: 8765)
    monkeypatch.setattr(R, "server_exe", lambda: "llama-server")
    monkeypatch.setattr(R, "model_path", lambda: "model")
    monkeypatch.setattr(R, "_pidfile", lambda: tmp_path / "pid")
    monkeypatch.setattr(R.subprocess, "Popen", lambda *a, **k: Proc())
    monkeypatch.setattr(R.urllib.request, "urlopen", lambda *a, **k: _Resp(b"{}"))
    monkeypatch.setattr(R.threading, "Thread", lambda **k: type("NoThread", (), {"start": lambda self: None})())
    with pytest.raises(R.SafetyBlocked, match="85 °C"):
        R.ensure_running()
    temp[0] = 84
    assert R.ensure_running() == "http://127.0.0.1:8765"
    assert R._server["tripped"] == "hot"   # last event is history, not a lockout
