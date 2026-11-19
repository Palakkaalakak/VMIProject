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
