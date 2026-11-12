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
    """The wrong-machine guard: everything between step 0 and step 1.

    ANCHORED ON THE STEP NUMBER, NOT ON ITS TITLE. This sliced to "# -- 1. STOP THE TASK",
    and the day that step learned to stop an NSSM service as well as a scheduled task its
    heading became "STOP WHATEVER SUPERVISES IT HERE" -- five tests then failed on a
    ValueError, about a guard that had not changed at all. A test that breaks when a comment
    is reworded is testing the comment.
    """
    at = _S.index("# -- 0. IS THIS THE MACHINE")
    return _S[at:_S.index("# -- 1. ", at)]


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


# ── what is listening is not what the task will bring back ───────────────────
#
# 14 Oct 2026: DESKTOP-GFAAP80 listened on 8071 only, and the refusal said "re-run here with
# -Port 8071". The laptop's scheduled task is installed for 8072; the last time "-Port 8071"
# was run there it ended a stray 8071 window, started the task on 8072, and reported 8071 as
# down. The remedy the guard offered was the fault the guard exists to prevent.

def test_the_tasks_own_port_is_read_before_anything_is_stopped():
    code = _code()
    read = code.index("Get-ScheduledTask -TaskName $TaskName")
    assert read < code.index("Stop-ScheduledTask"), (
        "the task's port is learned after the task has been stopped")
    assert re.search(r"-match '-Port\\s\+\(\\d\+\)'", _guard()), (
        "the guard does not read the -Port the scheduled task was installed with")


def test_a_listener_that_is_not_the_task_is_refused_before_it_is_ended():
    body = _guard()
    assert "$taskPort -ne $Port -and ($serving -contains $Port)" in body, (
        "a listener on the asked port that the task does not own is ended, and the task is "
        "brought back on another port")
    assert body.count("exit 2") >= 2
    assert "install-service-task.ps1 -Port" in body, (
        "no way offered to make the listening port the machine's own")


def test_asking_for_the_tasks_port_is_never_refused_as_the_wrong_machine():
    """The task IS what serves its port, even while it is down and another window holds a
    different one. Refusing that would leave no way to restart the machine's own service."""
    body = _guard()
    assert "($taskPort -ne $Port)" in body
    assert "is not the scheduled task; it is left alone" in body, (
        "the other listener is passed over in silence, still serving old code")


def test_the_refusal_offers_the_tasks_port_when_it_knows_it():
    body = _guard()
    assert "if ($taskPort -gt 0) { $offer = $taskPort }" in body, (
        "the remedy names whatever happens to be listening, not what the task starts")


# ── PowerShell faults that cannot be caught by running it on Linux ───────────

def test_no_if_statement_is_used_where_a_value_is_expected():
    """`if` is a statement in PowerShell, not an expression; `-ForegroundColor (if ...)` is a
    parse error, so the script would not run at all."""
    assert not re.search(r"-\w+\s+\(if\s", _S), (
        "an if-statement is being passed as a parameter value; assign it first")


def test_the_braces_and_parentheses_balance():
    assert _S.count("{") == _S.count("}"), "unbalanced braces"
    assert _S.count("(") == _S.count(")"), "unbalanced parentheses"


# ── A FAILED RESTART SAYS WHY, ON THE SCREEN (24 Oct) ───────────────────────────────────
# The laptop's restart reported "NOT answering on 8072. The reason is in service-<date>.log"
# twice while a second starter had the service up on 8071 and both wrote one log file.

def test_each_port_logs_to_its_own_file():
    start = (_PATH.parent / "start-service.ps1").read_text(encoding="utf-8-sig")
    assert '("service-" + $Port + "-" + (Get-Date -Format "yyyy-MM-dd") + ".log")' in start


def test_the_restart_polls_rather_than_waiting_eight_seconds():
    assert "Start-Sleep -Seconds 8" not in _S
    assert "(Get-Date).AddSeconds(60)" in _S and "while ((Get-Date) -lt $deadline)" in _S


def test_a_failed_restart_names_another_port_the_log_and_the_task_result():
    fail = _S[_S.index("NOT answering on $Port after 60 seconds."):]
    assert "foreach ($other in @(8071, 8072, 8073))" in fail
    assert "The service IS answering on" in fail
    assert "ParentProcessId" in fail, "the supervisor behind another port is named"
    assert "Get-ScheduledTaskInfo" in fail
    assert '"service-{0}-{1}.log" -f $Port, $day' in fail and "Select-Object -Last 25" in fail
    assert "service-<date>.log" not in fail, "a file is named, not described"


def test_the_scripts_stay_ascii():
    for name in ("restart-service.ps1", "start-service.ps1", "install-service-task.ps1"):
        text = (_PATH.parent / name).read_text(encoding="utf-8-sig")
        assert all(ord(c) < 128 for c in text), f"{name} must stay ASCII for PowerShell 5.1"
