"""Runs the dependency-free frontend unit tests (Node's built-in test runner)."""
import shutil
import subprocess
from pathlib import Path

import pytest

JS_TESTS = Path(__file__).resolve().parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_frontend_js_units():
    files = sorted(str(p) for p in JS_TESTS.glob("*.test.js"))
    assert files, "no JS test files found"
    proc = subprocess.run(
        ["node", "--test", *files],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
