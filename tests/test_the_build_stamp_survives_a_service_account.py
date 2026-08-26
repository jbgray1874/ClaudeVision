"""The service must report the build it is running, on a box where git answers only to a person.

SDI-APP01 served a current build and reported `"commit": "unknown"`. git works there from an
interactive shell — `git -C C:\\ClaudeVision rev-parse --short HEAD` returns the hash — but the
scheduled task runs under a different account, and from there git is either off the PATH or
refusing a repository somebody else cloned (`safe.directory`).

So the one field that exists to catch a stale deployment was the field that stopped working, on
the one host where two portals could drift apart. Three deployments on three commits already cost
a day this week; that is what this field is for.

The fix resolves the hash in start-service.ps1 — the task's own action, a PowerShell shell — and
hands it down through SDI_COMMIT, which app.py already checks before git.

WHAT WAS REJECTED, and why it is recorded here: pinning `SDI_COMMIT=<hash>` in .env. It is worse
than "unknown". "unknown" admits it does not know; a pinned hash keeps naming a build that
stopped running at the next deploy, and names it confidently. An absent answer costs a question;
a wrong one costs an afternoon.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_START = (_ROOT / "tools" / "start" / "start-service.ps1").read_text(encoding="utf-8")
_APP = (_ROOT / "sdi-intelligence-backend" / "app.py").read_text(encoding="utf-8")


def test_the_launcher_resolves_the_commit():
    assert "rev-parse" in _START and "SDI_COMMIT" in _START


def test_it_is_resolved_before_python_is_launched():
    """After the launch it stamps nothing — the child has already read its environment."""
    assert _START.index("SDI_COMMIT") < _START.index("& $python $app")


def test_the_app_prefers_the_handed_down_value_over_its_own_git():
    """app.py must read the environment first, or the fix does not reach it."""
    at = _APP.index("def _resolve_commit")
    body = _APP[at:_APP.index("SDI_COMMIT = _resolve_commit()")]
    assert body.index('os.getenv("SDI_COMMIT"') < body.index("rev-parse")


def test_an_already_set_value_is_not_overwritten():
    """A deploy with no working tree sets SDI_COMMIT itself; this must not clobber it."""
    assert "if (-not $env:SDI_COMMIT)" in _START


def test_git_is_found_by_path_and_by_location():
    """PATH first, because that is right when it works; explicit locations after, because the
    account the task runs as is exactly the one whose PATH may not carry git."""
    at = _START.index("if (-not $env:SDI_COMMIT)")
    block = _START[at:at + 1400]
    assert "Get-Command git" in block
    assert "Program Files\\Git\\cmd\\git.exe" in block


def test_it_asks_about_the_repo_root_not_the_script_folder():
    at = _START.index("rev-parse")
    assert "-C" in _START[at - 120:at], "must use git -C <root>, not the current directory"


def test_a_missing_git_never_stops_the_service():
    """A version string is not worth refusing to serve over. It degrades to the old behaviour."""
    at = _START.index("if (-not $env:SDI_COMMIT)")
    block = _START[at:at + 1600]
    assert "SilentlyContinue" in block
    assert "catch { }" in block
    assert "unresolved" in block, "it must say so rather than failing silently"


def test_the_stop_on_error_default_is_restored():
    """PowerShell 5.1 turns the first stderr line into a terminating error under EAP=Stop, which
    is what killed this service once already. The guard must be scoped, not left switched off."""
    at = _START.index("if (-not $env:SDI_COMMIT)")
    block = _START[at:at + 1600]
    assert 'ErrorActionPreference = "Continue"' in block
    assert "finally { $ErrorActionPreference = $prevEA }" in block


def test_no_hash_is_pinned_in_any_committed_env_file():
    """The rejected option, asserted so nobody adds it later. A committed SDI_COMMIT is a
    promise the repository cannot keep."""
    for env in _ROOT.rglob("*.env"):
        if ".venv" in env.parts or "_archive" in env.parts:
            continue
        text = env.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip().startswith("SDI_COMMIT="):
                value = line.split("=", 1)[1].strip()
                assert not re.fullmatch(r"[0-9a-f]{7,40}", value), (
                    f"{env} pins SDI_COMMIT={value} — it will misreport the build after the "
                    f"next deploy")
