"""A red error in the middle of a restart that had, in fact, worked.

WHAT HAPPENED, on SDI-App01:

    C:\\ClaudeVision\\tools\\start\\restart-service.ps1 -Port 8071
    Restarting the SDI Intelligence service on port 8071
      the scheduled task was not running
      ending pid 30724 (python, started 18:18:52)
      started the scheduled task
    restart-service.ps1 : The term 'git' is not recognized as the name of a cmdlet...

    Invoke-RestMethod http://localhost:8071/api/health | Select-Object -Expand status
    ok

The restart succeeded. The error came from the step that checks whether the running service
matches the checkout, which shells out to git — and SDI-APP01 has no git. Under
`$ErrorActionPreference = "Stop"` that is a CommandNotFoundException raised BEFORE the command
runs, so the `2>$null` beside it never gets a chance to suppress anything.

An error printed by a step that did not fail is how a working deploy gets rolled back.

THE SECOND HALF IS THE ONE THAT WAS ACTUALLY COSTING SOMETHING. Because git is absent, that
machine could never resolve its own commit, so `/api/health` reported

    "commit": "unknown"

and nothing could distinguish a current server from one serving files copied weeks ago. That
is the single question anybody asks after a deploy, and it is the question the whole restart
script exists to answer. It was open long enough to be written down as a known fault.

push-to-server.ps1 runs on the LAPTOP, which has git. So it now leaves the short hash in
`.sdi-commit` beside the code it copied. The answer travels with the deploy instead of being
recomputed where it cannot be.

AND THAT WAS NOT ENOUGH, WHICH IS THE SECOND LESSON HERE. Only the start SCRIPT read the
stamp, so on the next deploy:

    Test-Path C:\\ClaudeVision\\.sdi-commit    ->  True
    Get-Content C:\\ClaudeVision\\.sdi-commit  ->  9dbb44a
    /api/health                              ->  status ok, commit unknown

The stamp was there, correct, and ignored — because something other than start-service.ps1
had started the service. A service that can name its build only when launched one particular
way does not really know its build. app.py reads the file itself now, after git and before
giving up, so the answer does not depend on the launcher.

WHY THE STAMP IS WRITTEN AFTER THE COPY. A stamp written first would name a commit the server
does not have yet if the copy then failed — a confident wrong answer, which is worse than
"unknown". "unknown" costs a question; a wrong build number costs an afternoon.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_START = _ROOT / "tools" / "start"
_SCRIPTS = ("start-service.ps1", "restart-service.ps1", "install-service-task.ps1")


def _text(name: str) -> str:
    return (_START / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """The script with its commentary blanked, positions preserved.

    Every one of these files explains `& git` in a comment before using it, and a raw search
    matches the explanation first. That has now happened six times in this suite.
    """
    src = re.sub(r"<#.*?#>", lambda m: " " * len(m.group(0)), _text(name), flags=re.S)
    return "\n".join(" " * len(ln) if ln.lstrip().startswith("#") else ln
                     for ln in src.splitlines())


# ── nothing calls git in a way that can throw ────────────────────────────────

@pytest.mark.parametrize("name", _SCRIPTS)
def test_no_start_script_invokes_git_directly(name):
    """THE ASSERTION. `& git` is not a call that fails on a machine without git — it is a
    call that never happens, and raises instead."""
    hits = [ln.strip() for ln in _code(name).splitlines() if re.search(r"&\s+git\b", ln)]
    assert not hits, (
        f"{name} invokes git directly: {hits}. On a machine with no git that raises "
        f"CommandNotFoundException before the redirect applies, and prints a failure for a "
        f"step that succeeded.")


@pytest.mark.parametrize("name", _SCRIPTS)
def test_each_one_resolves_the_commit_through_the_helper(name):
    assert "Get-HeadCommit" in _text(name), f"{name} has no safe commit resolver"


@pytest.mark.parametrize("name", _SCRIPTS)
def test_the_helper_is_defined_before_it_is_used(name):
    """PowerShell runs a script top to bottom, so a function defined below its call site does
    not exist yet. The first version of this change put the helper after its own use in
    start-service.ps1 — which would have failed exactly like the fault it was fixing."""
    code = _code(name)
    define = code.index("function Get-HeadCommit")
    uses = [m.start() for m in re.finditer(r"=\s*Get-HeadCommit\b", code)]
    assert uses, f"{name} defines the helper and never calls it"
    assert define < min(uses), (
        f"{name} calls Get-HeadCommit at {min(uses)} before defining it at {define}")


@pytest.mark.parametrize("name", _SCRIPTS)
def test_the_helper_falls_back_to_the_stamp(name):
    body = _text(name)
    at = body.index("function Get-HeadCommit")
    fn = body[at:at + 1400]
    assert "Get-Command git" in fn, "git is not looked up before being called"
    assert ".sdi-commit" in fn, (
        "there is no fallback, so a machine without git still reports 'unknown' — which is "
        "the half of this that was actually costing something")


# ── the stamp is written where it can be, by something that knows ────────────

def test_push_to_server_leaves_the_commit_behind():
    push = _text("push-to-server.ps1")
    assert ".sdi-commit" in push, (
        "the deploy does not record which commit it copied, so the server cannot say")
    assert "rev-parse --short HEAD" in push


def test_the_stamp_is_written_after_the_copy_not_before():
    """A stamp written first names a commit the server does not have if the copy then fails.
    A confident wrong build number is worse than no build number."""
    push = _code("push-to-server.ps1")
    copied = push.index("Copy-Item -LiteralPath $c.Src")
    stamped = push.index(".sdi-commit")
    assert copied < stamped, "the commit is stamped before the files are copied"


def test_push_to_server_may_call_git_directly_because_it_cannot_run_without_it():
    """The one exception, stated so the rule above is not quietly widened later: this script
    takes its whole file list from `git ls-files` and refuses without it. It only ever runs on
    the laptop. That is why it is the thing that can write the stamp at all."""
    push = _code("push-to-server.ps1")
    assert "git ls-files" in push
    assert "push-to-server.ps1" not in _SCRIPTS, (
        "push-to-server is being held to the no-direct-git rule, which it cannot meet and "
        "does not need to")


# ── the service can answer without help from whatever launched it ────────────
#
# The stamp was in place on SDI-APP01 and correct:
#
#     Test-Path C:\ClaudeVision\.sdi-commit   ->  True
#     Get-Content C:\ClaudeVision\.sdi-commit ->  9dbb44a
#     /api/health                             ->  status ok, commit unknown
#
# Because only the START SCRIPT read it, and something else had started the service. A
# service that can name its build only when launched one particular way does not really
# know its build. app.py reads the stamp itself now.

_APP = (_ROOT / "sdi-intelligence-backend" / "app.py").read_text(encoding="utf-8")


def _resolver_body() -> str:
    at = _APP.index("def _resolve_commit")
    return _APP[at:_APP.index("SDI_COMMIT = _resolve_commit()")]


def test_the_service_reads_the_stamp_itself():
    """THE ASSERTION. Not via the launcher, not via an environment variable somebody has to
    remember to set."""
    assert ".sdi-commit" in _resolver_body(), (
        "app.py cannot read the deploy stamp, so it depends on being started by exactly one "
        "script to know what it is running")


def test_the_working_trees_own_head_still_wins():
    """On a real checkout HEAD is the truth and a stamp beside it may be stale. The fallback
    is for machines where there is nothing to ask — SDI-APP01 has no git AND no .git, because
    it is a copy rather than a clone."""
    body = _resolver_body()
    assert body.index("rev-parse") < body.index(".sdi-commit"), (
        "the stamp is consulted before git, so a stale file would outrank a live checkout")
    assert body.index('os.getenv("SDI_COMMIT"') < body.index("rev-parse"), (
        "an explicitly set SDI_COMMIT no longer wins, which deploys rely on")


def test_reading_the_stamp_cannot_break_startup():
    """This runs at import. Every other branch here is wrapped for the same reason: a version
    string must never be the thing that stops the service coming up."""
    body = _resolver_body()
    tail = body[body.index(".sdi-commit") - 400:]
    assert "except Exception" in tail, "an unreadable stamp file would raise at import"
    assert body.rstrip().endswith('return "unknown"'), (
        "the resolver no longer ends in a value, so a failure to resolve could propagate")
