"""Two tools that both look authoritative, disagreeing, and no way from either to find out which.

WHAT PROMPTED THIS, asked in four words: *"WHAT WAS THE DEGRADED BACKEND?"*

The portal header says BACKEND DEGRADED. That is `/api/health` reporting the service is UP but
NOT READY — one of five things it needs is missing. The badge shows only the summary word.

And the tool built to answer exactly this kind of question could not help:

    .\\.venv\\Scripts\\python.exe tools\\diagnose\\environment_check.py
    …
      Nothing wrong found. Every switch above came from somewhere named.

Both statements were true and they contradicted each other, because `environment_check` scans
`src/` and `tools/` — and the three settings that decide the badge are read by the BACKEND:

    SDI_FILE_ROOTS      sdi-intelligence-backend/config.py
    SDI_STAGING_ROOT    sdi-intelligence-backend/config.py
    SDI_WB_TEMPLATE     read straight from os.environ in app.py, not in config at all

A diagnostic with a blind spot is worse than no diagnostic over that spot, because "nothing
wrong found" is read as an all-clear rather than as "nothing wrong in the half I looked at".

WHAT IT DOES NOW. Computes the same five checks the endpoint does, from the same settings,
WITHOUT the service running and without the network — so it answers the question on a machine
where the portal will not start, which is exactly when somebody needs it.

WHAT THIS FILE PINS. That the two stay in step. If `/api/health` grows a sixth condition, the
diagnostic must grow it too, or the blind spot comes back one check smaller.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_APP = (_ROOT / "sdi-intelligence-backend" / "app.py").read_text(encoding="utf-8")
_CHECK_PATH = _ROOT / "tools" / "diagnose" / "environment_check.py"
_CHECK = _CHECK_PATH.read_text(encoding="utf-8")


def _health_conditions() -> str:
    """The `overall = (...)` expression — the definition of "degraded"."""
    at = _APP.index("overall = (")
    return _APP[at:_APP.index("\n    return", at)]


def test_the_endpoint_still_states_degraded_as_one_expression():
    """Everything below reads that expression. If it is ever spread across several
    statements, these assertions would silently check a fragment."""
    cond = _health_conditions()
    assert cond.count("and") >= 4, f"the health condition looks different now:\n{cond}"


# The response KEY is "database"; the condition reads the local `db`. Ask for what the
# expression actually says, or this guard passes on a rename it was written to catch.
@pytest.mark.parametrize("thing", ["roots_ok", "staging", "template", 'db["status"]'])
def test_the_endpoint_checks_what_this_test_thinks_it_checks(thing):
    """A guard on the guard: if a condition is renamed, the coverage test below would pass by
    comparing two empty sets."""
    assert thing in _health_conditions()


def test_the_diagnostic_covers_every_setting_the_badge_depends_on():
    """THE ASSERTION. Each of the three backend settings must be named in the diagnostic —
    it could not see any of them, which is how it printed an all-clear under a red badge."""
    missing = [k for k in ("SDI_FILE_ROOTS", "SDI_STAGING_ROOT", "SDI_WB_TEMPLATE")
               if k not in _CHECK]
    assert not missing, (
        f"environment_check does not look at {', '.join(missing)} — so it can print "
        f"'Nothing wrong found' while the header says BACKEND DEGRADED for exactly that reason.")


def test_the_diagnostic_reads_the_backend_env_and_not_only_the_engine_one():
    """These settings live in sdi-intelligence-backend/.env. Reading only the repo-root .env
    would report them all unset on a machine where they are set correctly — a false alarm,
    which is the other way to be useless."""
    assert 'ROOT / "sdi-intelligence-backend" / ".env"' in _CHECK, (
        "the diagnostic never opens the backend's own .env")


def test_it_checks_the_three_conditions_and_not_just_the_names():
    """Naming a setting and not testing it would pass the check above while telling nobody
    anything. Each has a distinct failure the endpoint cares about."""
    for probe, why in (
        ("os.path.isdir", "a file root or the staging folder has to be tested for existence"),
        ("os.path.isfile", "the workbook template is a FILE, not a folder"),
        ("startswith(_norm", "staging must be tested for CONTAINMENT inside the file roots — "
                             "an existing folder outside them still refuses every run"),
    ):
        assert probe in _CHECK, f"{probe} missing: {why}"


def test_the_mapped_drive_trap_is_still_called_out():
    """The first failure in the field: SDI_STAGING_ROOT as `K:\\...`. A drive letter belongs to
    a login session, so a service account has no such drive, and the error — "cannot find the
    path specified: 'K:\\'" — reads as a missing folder rather than a wrong KIND of path."""
    assert "mapped drive letter" in _CHECK
    assert "login session" in _CHECK


def test_the_double_space_in_the_template_name_is_stated():
    """`Blank Estimate Sheet  WB 2026.xlsx` has two spaces before WB. Somebody retyping the
    path from a screenshot produces a file that looks identical and is not found."""
    assert "DOUBLE SPACE" in _CHECK.upper()
    default = re.search(r"_WB_TEMPLATE_DEFAULT\s*=\s*\((.*?)\)\n", _CHECK, re.S)
    assert default and "Sheet  WB" in default.group(1).replace("\\\\", "\\"), (
        "the diagnostic's copy of the default template path has lost the double space")


def test_the_two_copies_of_the_default_paths_agree():
    """The diagnostic holds its own copy of the two defaults, because importing the backend's
    config raises when SDI_FILE_ROOTS is unset — which is one of the states being diagnosed.
    A copy that drifts would diagnose a path the service never looks at."""
    def default(source: str, name: str) -> str:
        m = re.search(rf"{name}\s*=\s*\((.*?)\)\n", source, re.S)
        assert m, f"{name} not found"
        return "".join(re.findall(r'r"([^"]*)"', m.group(1))).replace("\\\\", "\\")

    assert default(_CHECK, "_WB_TEMPLATE_DEFAULT") == default(_APP, "_WB_TEMPLATE_DEFAULT"), (
        "the diagnostic and app.py disagree about where the workbook template lives")


def test_the_report_says_which_of_the_five_it_did_not_test():
    """The database is the fifth condition and this report does not test it — that needs
    --db, which costs a VPN round trip. Saying so is the difference between a report that
    covered four of five and a report that looks like it covered all five. Silent partial
    coverage is what made the old all-clear misleading in the first place."""
    at = _CHECK.index("def report_backend_readiness")
    body = _CHECK[at:_CHECK.index("\ndef ", at + 10)]
    assert "--db" in body or "database" in body.lower(), (
        "the readiness report checks four of the five conditions and never mentions the "
        "fifth, so a clean report reads as a clean bill of health")


def test_the_diagnostic_still_parses_and_is_runnable():
    ast.parse(_CHECK)
    # Called at all — matched on the name plus an open paren rather than an exact argument
    # list, which is what the first version pinned and which broke the moment the function
    # took one more parameter. A test that fails on a signature change it does not care about
    # trains people to edit the test rather than read it.
    calls = [m for m in re.finditer(r"report_backend_readiness\(", _CHECK)]
    assert len(calls) >= 2, (
        "the readiness report is defined but never called — the failure mode this whole "
        "suite keeps finding")
