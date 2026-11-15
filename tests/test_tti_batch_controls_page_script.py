"""The batch-controls page script, exercised in node: no auto-submit, the row link only selects,
an uncertain POST is not retried, and a rerun needs its replacement consent."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_the_page_script_behaves():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed here")
    script = ROOT / "sdi-intelligence-backend" / "tti-batch-controls.js"
    assert subprocess.run([node, "--check", str(script)], capture_output=True, text=True).returncode == 0
    done = subprocess.run([node, str(ROOT / "tests" / "js" / "test_tti_batch_controls_ui.cjs")],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
