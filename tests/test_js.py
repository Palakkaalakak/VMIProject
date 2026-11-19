"""Runs the small Node smoke tests for pure browser logic (skipped when Node is not installed)."""
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent / "js"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
@pytest.mark.parametrize("script", sorted(p.name for p in JS.glob("*.mjs")))
def test_js(script):
    r = subprocess.run(["node", script], cwd=JS, capture_output=True, text=True)
    assert r.returncode == 0 and "FAIL" not in r.stdout, r.stdout + r.stderr
