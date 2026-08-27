"""The obvious fix for "two files disagree about a password" is to copy it across. That is wrong.

WHAT HAPPENED. The header said BACKEND DEGRADED and the database detail said "Login failed for
user 'AIBot'", while `environment_check --db` on the same laptop reported REACHED. Two files
called .env, read in opposite orders:

    engine   src/config.py    repo-root .env, then src/.env — RETURNS on the first hit
    backend  config.py        its OWN .env FIRST, then the repo root, override=False → first wins

A rotation applied at the root was taken by the engine and SHADOWED for the service by a
13-character AIAgentPW2026 sitting beside it.

WHY COPYING IT ACROSS IS THE WRONG FIX. Two copies of a secret is what caused this. A third
write of the same value resets the clock and nothing else — the next rotation breaks exactly one
process again, in exactly the same way, and the person doing it will have no more reason to
suspect the second file than we did.

The service reads the repo-root .env as its SECOND layer. Delete the duplicate and it falls
through to the shared one: ONE place to rotate, permanently. That is what tools/start/
one-db-password.ps1 does.

WHY THIS FILE EXISTS. There is no PowerShell in the environment this was written in, so the
script could not be executed before it was handed over — and it edits a live credential file on
a machine that cannot be reached. Everything here is what could be checked without running it:
that it backs up first, that it refuses the case where the fix would leave no password at all,
that it never prints the value, and that it writes without a byte-order mark.

THE BOM ONE IS NOT THEORETICAL. `Set-Content -Encoding UTF8` emits a BOM on Windows PowerShell
5.1. python-dotenv would then read the file's FIRST key as "\\ufeffSDI_..." — corrupting a
setting at random in the very file being edited to repair a configuration fault. The .NET
WriteAllLines default has no BOM, which is why it is used instead.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT_PATH = _ROOT / "tools" / "start" / "one-db-password.ps1"
_S = _SCRIPT_PATH.read_text(encoding="utf-8")


# ── it removes a copy, it does not make one ───────────────────────────────────

def test_it_never_writes_the_password_into_the_other_file():
    """THE ASSERTION. The whole point is one copy, not two that agree today."""
    body = _S[_S.index("# ── change it"):]
    for copying in ("$rootVal", "= $rootVal", "$Key=$rootVal"):
        assert copying not in body, (
            f"the edit section references {copying} — if it writes the root's value into the "
            f"service's .env it has made the two-copy problem again with a fresh timestamp")


def test_it_comments_the_line_out_rather_than_deleting_it():
    """A deleted line leaves nobody able to see what was there. A commented one dated with
    the reason is a note to whoever finds it next."""
    assert '$out.Add("# $line")' in _S, "the original line is not preserved as a comment"
    assert "SHADOWED" in _S, "the commented-out line carries no reason"


def test_it_stops_the_only_way_this_could_do_harm():
    """If the repo-root .env has no password, removing the service's copy leaves it with NONE.
    That turns a wrong password into no password, which is worse and looks the same."""
    assert 'if ($null -eq $rootVal -or $rootVal -eq "")' in _S
    at = _S.index('if ($null -eq $rootVal')
    guard = _S[at:at + 600]
    assert "STOP" in guard and "exit 2" in guard, (
        "the guard does not actually stop — it must refuse, not warn and continue")


def test_it_backs_the_file_up_before_touching_it():
    edit = _S.index("# ── change it")
    write = _S.index("WriteAllLines")
    backup = _S.index("Copy-Item")
    assert edit < backup < write, "the backup is not taken before the file is rewritten"
    assert ".bak" in _S and "Get-Date -Format" in _S, "the backup is not timestamped"


# ── it cannot leak what it is diagnosing ──────────────────────────────────────

def test_only_lengths_are_ever_printed():
    """This writes to a terminal that gets screenshotted and pasted into chat — which is how
    the whole conversation about this password has been conducted."""
    for line in _S.splitlines():
        if "Write-Host" not in line or line.strip().startswith("#"):
            continue
        for bare in ("$rootVal", "$beVal"):
            if bare not in line:
                continue
            # Passing it through the formatter is the safe shape — that is what reduces a
            # value to "N chars". A bare interpolation is not.
            assert "& $show" in line or ".Length" in line, (
                f"a Write-Host could print the value itself: {line.strip()}")
    assert '"$($v.Length) chars"' in _S, "the formatter does not reduce values to a length"


# ── PowerShell faults that cannot be caught by running it on Linux ────────────

def test_it_writes_without_a_byte_order_mark():
    """Set-Content -Encoding UTF8 emits one on PS 5.1, and python-dotenv would read the first
    key as '\\ufeffSDI_...'. Corrupting a setting at random in the file being repaired."""
    assert "[System.IO.File]::WriteAllLines" in _S
    # THE LINE, not the match. `m.group(0).lstrip()` starts at "Set-Content" — it can never
    # begin with '#', so a mention inside a COMMENT explaining why Set-Content is avoided was
    # reported as a use of it. That is the fourth time in this suite a text search has been
    # fooled by prose about the thing it was searching for.
    writes = [ln.strip() for ln in _S.splitlines()
              if "Set-Content" in ln and not ln.strip().startswith("#")]
    assert not writes, f"Set-Content is used to write the .env: {writes}"


def test_no_if_statement_is_used_where_a_value_is_expected():
    """`if` is a statement in PowerShell, not an expression. `-ForegroundColor (if ...)` is a
    PARSE error — the script would not run at all, and there is no PowerShell in the
    environment it was written in to catch that."""
    assert not re.search(r"-\w+\s+\(if\s", _S), (
        "an if-statement is being passed as a parameter value; assign it first")


def test_the_braces_and_parentheses_balance():
    """The cheapest possible stand-in for a parser. It would not catch a subtle fault; it
    catches the one that makes a script fail on line 1."""
    assert _S.count("{") == _S.count("}"), "unbalanced braces"
    assert _S.count("(") == _S.count(")"), "unbalanced parentheses"


# ── it proves the fix rather than assuming it ─────────────────────────────────

def test_it_restarts_before_checking():
    """.env is read once at process start. An edited file with no restart looks exactly like
    an edit that did not work — which is its own afternoon, and one already spent."""
    assert "restart-service.ps1" in _S
    assert _S.index("restart-service.ps1") < _S.index("/api/health"), (
        "the health check runs before the restart, so it would report the OLD process")


def test_it_reports_what_is_still_wrong_rather_than_declaring_success():
    """Four other conditions can hold the badge red. A script that fixes one and says "done"
    sends somebody back to the browser to find out it is still red."""
    tail = _S[_S.index("# ── prove it"):]
    assert "staging" in tail and "workbook_template" in tail, (
        "the verification does not mention the other conditions behind the badge")
    assert "restores the previous state" in tail, (
        "nothing tells the reader the backup is how to undo this")


def test_looking_is_the_default_and_changing_is_opt_in():
    """It edits a live credential file. The default must be to report."""
    assert "[switch]$Apply" in _S
    assert "if (-not $Apply)" in _S, "there is no read-only path"
