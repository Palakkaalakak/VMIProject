"""Which code is this: the git commit of the checkout ("abc1234 2026-11-16 subject"), read once; "unknown" outside git."""
import subprocess

from vmi.config import ROOT

_CACHE: dict = {}


def version() -> str:
    if not _CACHE:
        try:
            _CACHE["v"] = subprocess.run(["git", "log", "-1", "--format=%h %cs %s"], cwd=ROOT, capture_output=True, text=True,
                                         timeout=5).stdout.strip() or "unknown"
        except Exception:
            _CACHE["v"] = "unknown"
    return _CACHE["v"]
