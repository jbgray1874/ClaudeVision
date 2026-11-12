"""Two files called .env, read in opposite orders by two processes, on one machine.

WHAT HAPPENED. The SDILive password was rotated and put in the repo-root `.env`. Then:

    environment_check --db          Price source (SDILive) : REACHED
    GET /api/health                 "Login failed for user 'AIBot'"   → BACKEND DEGRADED

Same laptop, same login, same server, same instant. One process could authenticate and the
other could not, and neither message contained the fact that would explain it.

WHY. There are two files called `.env` and the two processes read them in OPPOSITE orders:

    engine   src/config.py            repo-root .env, then src/.env — RETURNS on the first hit
    backend  sdi-intelligence-backend/config.py
                                      its OWN .env first, then the repo-root one, with
                                      python-dotenv override=False — so FIRST WINS

So a rotation applied only at the root is picked up by the engine and SHADOWED for the service
by a 13-character `AIAgentPW2026` sitting beside it. Everything downstream is correct behaviour
producing a wrong outcome: the file is read, the value is used, the login is refused.

WHAT THE MESSAGE COULD NOT TELL YOU. "Login failed for user 'AIBot'" is what SQL Server says
when the password is wrong. It is also what it says when the password is RIGHT and a different
file supplied a different one. The message cannot distinguish "you typed it wrong" from "you
fixed the wrong file", and those need opposite responses — one sends you to SSMS to reset a
password that is already correct.

THE FIX IS NOT A CODE PATH, IT IS A SENTENCE. The service already knows which files it loaded;
it printed them at startup and then threw the list away. Keeping it, and naming it on a login
failure, turns a twenty-minute hunt into a glance. Filenames only — never the value.

This is the same principle as `require_db_password()` naming the file it wants the password
added to, and it is the third time the two-.env split has cost time.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _ROOT / "sdi-intelligence-backend"
_APP = (_BACKEND / "app.py").read_text(encoding="utf-8")
_CFG = (_BACKEND / "config.py").read_text(encoding="utf-8")
_ENGINE_CFG = (_ROOT / "src" / "config.py").read_text(encoding="utf-8")


def _db_status() -> str:
    tree = ast.parse(_APP)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "db_status":
            return "\n".join(_APP.splitlines()[node.lineno - 1:node.end_lineno])
    raise AssertionError("db_status not found")


# ── the failure names its source ───────────────────────────────────────────────

def test_the_service_keeps_the_list_of_files_it_loaded():
    """It printed them at startup and threw the list away. By the time a credential is being
    argued about, that line has scrolled off."""
    assert "ENV_LAYERS = list(_loaded)" in _CFG, (
        "config.py no longer keeps the loaded-layer list, so a failure cannot name it")


def test_a_login_failure_says_which_files_the_password_could_have_come_from():
    """THE ASSERTION. Not a new check, a new sentence on an existing one."""
    body = _db_status()
    assert "ENV_LAYERS" in body, "the DB failure does not consult the loaded-layer list"
    assert "credential_from" in body, "the failure payload does not name the files"


def test_it_says_first_wins_and_that_a_restart_is_needed():
    """The two facts somebody needs and cannot infer: which of the two files is authoritative,
    and that editing it is not enough because .env is read once at process start."""
    body = _db_status()
    assert re.search(r"FIRST of these files", body), (
        "the note does not say which layer supplies the value")
    assert "RESTART" in body, (
        "the note does not say the service must be restarted — .env is read at start, so an "
        "edited file with no restart looks exactly like an edit that did not work")


def test_the_note_only_fires_on_an_authentication_failure():
    """A timeout or a missing driver is not a wrong-file problem, and offering that advice
    would send somebody to edit a file that is already correct."""
    body = _db_status()
    assert '"Login failed" in' in body, (
        "the note is attached to every database error, not just authentication")


def test_the_value_is_never_returned():
    """The whole point is filenames. A payload that helpfully included the password would be
    served to any browser that opens the portal."""
    body = _db_status()
    # The NAME is allowed and is the point — the note has to say which key to edit. What must
    # never appear is a read of the VALUE, or the connection string it is interpolated into.
    for leak in ("config.DB_PASSWORD", "DB_PASSWORD}", "db_connection_string()}", "PWD="):
        assert leak not in body, f"the failure payload could carry {leak}"
    assert "SDI_DB_PASSWORD" in body, (
        "the note should name the KEY to edit — telling somebody a file is wrong without "
        "saying which line is half an answer")


def test_the_user_and_server_are_named_because_they_narrow_it():
    """"Login failed for user 'AIBot'" against which server? Two environments with the same
    login is the other way to spend an afternoon."""
    body = _db_status()
    assert "config.DB_USER" in body and "config.DB_SERVER" in body


# ── the split that caused it, recorded so it is not rediscovered ──────────────

def test_the_two_processes_still_read_the_two_files_in_opposite_orders():
    """Not a fault to fix — each order is right for its own process — but the FACT is what
    makes a root-only rotation break exactly one of them, and it is invisible from either
    file. If this ever changes, the explanation above stops being true and the note this
    test guards would be misleading."""
    # The engine: repo root first, then src/, returning on the first hit.
    assert re.search(r"\(BASE_DIR / \"\.env\",\s*Path\(__file__\)\.resolve\(\)\.parent / \"\.env\"\)",
                     _ENGINE_CFG), "src/config.py no longer looks in the repo root first"
    # The service: its own .env first, then the repo root, override=False so first wins.
    layers = _CFG[_CFG.index("_layers = ["):_CFG.index("]", _CFG.index("_layers = ["))]
    own = layers.index('_HERE / ".env"')
    root = layers.index('_HERE.parent / ".env"')
    assert own < root, "the service no longer reads its own .env before the shared one"
    assert "override=False" in _CFG, (
        "override=False is what makes the FIRST file win; without it the last would, and the "
        "note about shadowing would be backwards")


def test_the_architecture_page_describes_the_shadowing_and_not_only_the_engine():
    """The page was corrected today to say the ENGINE never reads the backend's .env. True,
    and only half of it — the half that bit is the reverse: for the SERVICE, a value beside it
    shadows the shared one, which is what a root-only rotation runs into."""
    portal = (_BACKEND / "sdi-intelligence-portal.html").read_text(encoding="utf-8")
    at = portal.index('id="architecture"')
    page = portal[at:portal.index('id="rnd"')]
    assert re.search(r"shadow", page, re.I), (
        "the config layering table does not mention that a value beside the service shadows "
        "the shared one — which is the direction that caused BACKEND DEGRADED")
