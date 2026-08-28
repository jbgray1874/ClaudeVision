"""A restart that succeeded, reported as a failure, on the machine nobody meant to touch.

WHAT HAPPENED.

    PS C:\\CLaudeVision> C:\\ClaudeVision\\tools\\start\\restart-service.ps1 -Port 8071
    Restarting the SDI Intelligence service on port 8071
      stopped the scheduled task
      ending pid 5416 (python, started 04:13:12)
      started the scheduled task

      NOT answering on 8071.
      The reason is in C:\\ClaudeVision\\output\\logs\\service-<date>.log

    PS C:\\CLaudeVision> hostname
    DESKTOP-GFAAP80

That was the LAPTOP, which serves 8072. SDI-APP01 serves 8071. The restart worked perfectly
— `/api/health` on 8072 returned `ok` a minute later — but `-Port` drives only the kill and
the health check, while the scheduled task is machine-wide and gets restarted regardless. So
the script stopped a healthy service, started it again, looked at a port that machine has
never served, and announced a failure.

WHY THAT IS EXPENSIVE RATHER THAN UNTIDY. The reasonable reading of "NOT answering on 8071"
is that the SERVER is broken. It sends somebody to a log on a machine where nothing is wrong,
while the machine they meant to restart has not been touched. Both boxes have a
C:\\ClaudeVision and both prompts read the same, so there is nothing on screen to tell them
apart — this session lost several rounds to exactly that, including a `git pull` and a `pip
install` run against the wrong computer.

THE CHECK RUNS BEFORE ANYTHING IS STOPPED. Refusing after the kill would leave the same mess
with a better message; the point is that the service that was running is still running.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / "tools" / "start" / "restart-service.ps1"
_S = _PATH.read_text(encoding="utf-8")


def _guard() -> str:
    at = _S.index("# -- 0. IS THIS THE MACHINE")
    return _S[at:_S.index("# -- 1. STOP THE TASK", at)]


def _code() -> str:
    """The script with its commentary removed.

    The ordering test below asks where Stop-ScheduledTask appears. Against the raw file it
    found it at offset 256 — inside the header comment, which explains what the script does
    before doing any of it. That is the sixth time in this suite a text search has matched
    prose ABOUT the thing rather than the thing, so the prose comes out first. Order is
    preserved by blanking the comments rather than deleting them.
    """
    without_header = re.sub(r"<#.*?#>", lambda m: " " * len(m.group(0)), _S, flags=re.S)
    return "\n".join(
        " " * len(line) if line.lstrip().startswith("#") else line
        for line in without_header.splitlines())


# ── it refuses, and refuses in time ──────────────────────────────────────────

def test_the_machine_is_checked_before_anything_is_stopped():
    """THE ASSERTION. Order is the whole point: a refusal printed after the service has been
    killed has not prevented the failure, it has narrated it."""
    code = _code()
    guard = code.index("$serving = @()")
    stop_task = code.index("Stop-ScheduledTask")
    kill = code.index("Stop-Process") if "Stop-Process" in code else len(code)
    assert guard < stop_task, "the machine check runs after the scheduled task is stopped"
    assert guard < kill, "the machine check runs after the listening process is killed"


def test_it_exits_rather_than_warning_and_continuing():
    body = _guard()
    assert "exit 2" in body, (
        "the wrong-machine case warns and carries on, which is what it already did")
    assert "Nothing has been stopped" in body, (
        "nothing tells the reader the service is untouched — without that they will go and "
        "check, which is the cost this guard exists to avoid")


def test_it_only_fires_when_the_machine_serves_something_else():
    """A machine with the service genuinely DOWN listens on nothing, and restarting it is
    exactly right. Refusing there would break the one case the script is for."""
    body = _guard()
    assert "$serving.Count -gt 0" in body, (
        "the guard fires when nothing is listening at all — which is a service that needs "
        "restarting, not a wrong machine")
    assert "-notcontains $Port" in body


# ── it says which machine, and which port, because that is the confusion ─────

def test_it_names_the_machine_it_is_running_on():
    """"Wrong machine" is useless when both prompts read C:\\ClaudeVision. The hostname is
    the only thing on screen that distinguishes them."""
    body = _guard()
    assert "GetHostName()" in body, "the refusal does not say which machine this is"


def test_it_states_which_port_belongs_to_which_box():
    body = _guard()
    assert "8072" in body and "8071" in body, "the message does not map ports to machines"
    assert re.search(r"laptop serves 8072", body), "the laptop's port is not stated"
    assert re.search(r"SDI-APP01 serves 8071", body), "the server's port is not stated"


def test_it_offers_both_ways_out():
    """Two different intentions produce this: right machine wrong flag, or right flag wrong
    machine. Naming only one of them sends half the readers the wrong way."""
    # Both compared in lower case. The script emphasises "run this ON the other machine",
    # and a case-sensitive search for the same words failed on the text that was correct.
    body = _guard().lower()
    assert "re-run here with -port" in body, "the wrong-flag case has no remedy"
    assert "on the other machine" in body, "the wrong-machine case has no remedy"


# ── PowerShell faults that cannot be caught by running it on Linux ───────────

def test_no_if_statement_is_used_where_a_value_is_expected():
    """`if` is a statement in PowerShell, not an expression; `-ForegroundColor (if ...)` is a
    parse error, so the script would not run at all."""
    assert not re.search(r"-\w+\s+\(if\s", _S), (
        "an if-statement is being passed as a parameter value; assign it first")


def test_the_braces_and_parentheses_balance():
    assert _S.count("{") == _S.count("}"), "unbalanced braces"
    assert _S.count("(") == _S.count(")"), "unbalanced parentheses"
