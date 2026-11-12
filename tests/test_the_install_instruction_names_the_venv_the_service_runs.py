"""Two virtualenvs on one machine, and the instructions named the one that does not run it.

WHAT HAPPENED. On SDI-APP01:

    PS C:\\ClaudeVision> .\\.venv\\Scripts\\python.exe -m pip install -r sdi-intelligence-backend\\requirements.txt
    .\\.venv\\Scripts\\python.exe : The term '.\\.venv\\Scripts\\python.exe' is not recognized...

That reads as a typo. It is not. There are TWO virtualenvs and they are not interchangeable:

    sdi-intelligence-backend\\.venv    the SERVICE. start-service.ps1 launches app.py with
                                       this one, and throws if it is missing.
    .venv  (repo root)                 the ENGINE. estimate_routes shells out to it to run
                                       an estimate (SDI_ENGINE_PYTHON).

SDI-APP01 has no engine virtualenv, because it QUEUES estimates and never runs one — no
SOLIDWORKS seat, no Excel, no runner. So the command is not misspelled, it is addressed to an
environment that has no reason to exist on that machine.

AND THE MANIFEST ITSELF SAID THE WRONG ONE. requirements.txt's header read "Install into the
ENGINE's virtualenv rather than a second one" — an intention that start-service.ps1 does not
implement. Following it on the laptop installs the service's dependencies into the engine's
environment, where the service will never look, and the service keeps working only because
its own virtualenv already had them.

That is the failure this repository keeps finding: an instruction that is confidently wrong is
worse than a missing one, because nobody re-derives it. So the paths are pinned here rather
than restated in prose — start-service.ps1 is the authority, because it is the thing that
actually launches the process.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_START = (_ROOT / "tools" / "start" / "start-service.ps1").read_text(encoding="utf-8")
_PUSH = (_ROOT / "tools" / "start" / "push-to-server.ps1").read_text(encoding="utf-8")
_REQS = (_ROOT / "sdi-intelligence-backend" / "requirements.txt").read_text(encoding="utf-8")
_ROUTES = (_ROOT / "sdi-intelligence-backend" / "estimate_routes.py").read_text(encoding="utf-8")

# THE AUTHORITY. Not what a comment says the service uses — what the script that starts it
# passes to the interpreter.
_SERVICE_VENV = "sdi-intelligence-backend\\.venv\\Scripts\\python.exe"


def test_the_service_is_launched_from_its_own_virtualenv():
    """The premise. If this ever moves, every instruction below is pointing at the old one."""
    assert '$python = Join-Path $Root "sdi-intelligence-backend\\.venv\\Scripts\\python.exe"' in _START, (
        "start-service.ps1 no longer launches app.py from the backend's virtualenv — "
        "re-derive which environment the dependencies belong in before editing this test")


def test_the_engine_virtualenv_is_a_different_one_and_still_is():
    """The two are not the same and the distinction is the whole point. The engine's is what
    an ESTIMATE is shelled out to; a machine that only queues has no use for it."""
    assert '"SDI_ENGINE_PYTHON", str(_REPO_ROOT / ".venv" / "Scripts" / "python.exe")' in _ROUTES, (
        "the engine interpreter is no longer the repo-root .venv, so the two-virtualenv "
        "explanation in these instructions has stopped being true")


def test_the_manifest_tells_you_to_install_where_the_service_will_look():
    """THE ASSERTION. The header said the engine's, which is an environment the service never
    reads and which does not exist on the server at all."""
    assert _SERVICE_VENV in _REQS, (
        "requirements.txt does not name the virtualenv the service is launched from")
    # The old instruction, verbatim, as the thing that must not come back.
    assert "Install into the ENGINE's virtualenv" not in _REQS, (
        "the manifest still directs its own dependencies into the engine's environment")


def test_the_push_script_names_the_same_one():
    """It prints the pip line after a copy, so it is the instruction most likely to be
    followed without thinking — which is exactly when a wrong path costs an evening."""
    assert _SERVICE_VENV in _PUSH, (
        "push-to-server.ps1 prints an install command for the wrong virtualenv")


@pytest.mark.parametrize("source,name", [(_REQS, "requirements.txt"),
                                         (_PUSH, "push-to-server.ps1")])
def test_neither_offers_the_bare_root_venv_as_the_install_target(source, name):
    """`.\\.venv\\Scripts\\python.exe -m pip install` is the exact command that failed on the
    server. It must not appear as an instruction in either place."""
    # THE LOOKBEHIND IS THE WHOLE PATTERN. Both paths end in the same fourteen characters —
    # `\.venv\Scripts\python.exe` — so the only thing separating the wrong instruction from
    # the right one is what precedes it. The first version of this line was escaped for a raw
    # file read as though it were a raw string, matched nothing at all, and passed against
    # the exact command that had just failed on the server. A guard that cannot fail is not
    # a guard, so it is checked against both spellings below.
    pattern = r"(?<!backend)\\\.venv\\Scripts\\python\.exe\s+-m\s+pip\s+install"
    assert re.search(pattern, r".\.venv\Scripts\python.exe -m pip install -r reqs.txt"), (
        "this test's own pattern no longer matches the command that failed")
    assert not re.search(pattern, r".\sdi-intelligence-backend\.venv\Scripts\python.exe -m pip install -r reqs.txt"), (
        "this test's own pattern rejects the CORRECT command, so it would fail on a fix")
    bad = re.search(pattern, source)
    assert not bad, (
        f"{name} still offers a pip install against the repo-root .venv: {bad.group(0)!r} — "
        f"that is the ENGINE's environment, and on SDI-APP01 it does not exist")


def test_the_reason_is_written_down_and_not_just_the_path():
    """A corrected path with no explanation gets 'corrected' back by the next person who
    remembers the old one. The comment in the requirements header has to say why."""
    assert "SDI-APP01 has" in _REQS and "no engine virtualenv" in _REQS, (
        "the manifest gives the right path without saying why the other one is wrong")
