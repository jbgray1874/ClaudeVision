"""There are two files called .env in this repo, and the service read only one of them.

The engine's lives at the repo root; the backend's lives beside the backend. "Put it in .env"
means the root one to anybody who has been working in C:\\ClaudeVision all day — and settings
added there were read by nothing. The service reported the feature as "not configured" while
the file plainly contained the line configuring it, and the startup log said `.env` either way
because it printed the bare filename.

That is not a mistake somebody makes once. Both are now read, most specific first.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CONFIG = _ROOT / "sdi-intelligence-backend" / "config.py"


def _loader_only() -> str:
    """The dotenv-layering half of config.py, without the settings that need a real .env."""
    src = _CONFIG.read_text(encoding="utf-8")
    head = src.split("def _req(")[0]
    assert "load_dotenv" in head, "the layering must still live above _req"
    return head


def _run(tmp_path: Path, root_env: str, backend_env: str | None, ask: str) -> str:
    """Build a throwaway checkout with one or two .env files and report what config sees."""
    backend = tmp_path / "sdi-intelligence-backend"
    backend.mkdir(parents=True, exist_ok=True)
    (tmp_path / ".env").write_text(root_env, encoding="utf-8")
    if backend_env is not None:
        (backend / ".env").write_text(backend_env, encoding="utf-8")

    probe = backend / "probe.py"
    probe.write_text(_loader_only() + textwrap.dedent(f"""
        import os
        print("VALUE=" + str(os.getenv({ask!r})))
    """), encoding="utf-8")

    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("SDI_")}
    out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout


pytestmark = pytest.mark.skipif(not _CONFIG.is_file(), reason="backend config not present")


def test_a_setting_in_the_repo_root_env_is_read(tmp_path):
    """THE DEFECT. SDI_DM_API_BASE was added to C:\\ClaudeVision\\.env and the service went on
    reporting the Document Manager as unconfigured."""
    out = _run(tmp_path, "SDI_DM_API_BASE=http://from-root:8000\n", None, "SDI_DM_API_BASE")
    assert "VALUE=http://from-root:8000" in out


def test_the_service_specific_file_still_wins(tmp_path):
    """More specific beats shared. A machine that needs the service to differ from the engine
    must still be able to say so."""
    out = _run(tmp_path,
               "SDI_DM_API_KEY=from-the-root\n",
               "SDI_DM_API_KEY=beside-the-service\n",
               "SDI_DM_API_KEY")
    assert "VALUE=beside-the-service" in out


def test_the_two_files_can_be_told_apart_in_the_startup_line(tmp_path):
    """Both are called '.env'. Printing the bare name made a file that had been read and one
    that had not look identical — which is exactly how the defect stayed hidden."""
    out = _run(tmp_path, "SDI_DM_API_BASE=x\n", "SDI_DM_API_BASE=y\n", "SDI_DM_API_BASE")
    line = next(ln for ln in out.splitlines() if ln.startswith("[config]"))
    assert line.count(".env") >= 2
    assert "sdi-intelligence-backend\\.env" in line, "the folder must name which .env it was"


def test_the_real_environment_still_beats_both_files(tmp_path):
    """load_dotenv(override=False) — anything already exported wins, which is what lets a
    one-off run be overridden without editing a file."""
    backend = tmp_path / "sdi-intelligence-backend"
    backend.mkdir(parents=True)
    (tmp_path / ".env").write_text("SDI_DM_API_BASE=from-a-file\n", encoding="utf-8")
    probe = backend / "probe.py"
    probe.write_text(_loader_only() + 'import os\nprint("VALUE=" + str(os.getenv("SDI_DM_API_BASE")))\n',
                     encoding="utf-8")
    env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("SDI_")}
    env["SDI_DM_API_BASE"] = "from-the-shell"
    out = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, env=env)
    assert "VALUE=from-the-shell" in out.stdout
