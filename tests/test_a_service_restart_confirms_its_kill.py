r"""A service restart confirms its kill, and stops every supervisor it finds (5 Nov 2026).

WHAT HAPPENED, on the laptop, after a sync to 007148b7:

    PS C:\ClaudeVision> .\tools\start\restart-service.ps1 -Port 8071 -TaskName "SDI Intelligence Service 8071"
      the scheduled task 'SDI Intelligence Service 8071' was not running
      ending pid 4136 (python, started unknown)
      started the scheduled task

      STILL STALE: serving 17513e4, this checkout is at 007148b7.
      Something took the port again.

Nothing had taken it. Pid 4136, started at 08:33 that morning, was still the listener: the
kill had been refused, and Stop-Process ran with SilentlyContinue, so the script printed
"ending", started a task that could not get the port, and blamed a stranger. "Started
unknown" was the clue it threw away: Get-Process cannot read the start time of a process
another account owns, which is the same reason the kill failed.

The same afternoon showed the second gap. The laptop has the scheduled task AND an NSSM
service, SDIIntelligence. The script stopped the task OR the service, never both, so a
running service would have brought the old code straight back after the kill.

The runner's restart script learned "a kill is confirmed, not assumed" on 23 Sep. The
service script is held to the same rule here.
"""
from __future__ import annotations

import re
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "start" / "restart-service.ps1"
_S = _PATH.read_text(encoding="utf-8")


def _code() -> str:
    """Prose blanked, length kept, so offsets still mean order."""
    without_header = re.sub(r"<#.*?#>", lambda m: " " * len(m.group(0)), _S, flags=re.S)
    return "\n".join((" " * len(ln)) if ln.lstrip().startswith("#") else ln
                     for ln in without_header.split("\n"))


def _step(n: int) -> str:
    code = _code()
    at = _S.index(f"# -- {n}. ")
    return code[at:_S.index(f"# -- {n + 1}. ", at)]


def test_the_kill_is_not_silenced():
    kill = _step(2)
    assert "Stop-Process -Id $procId -Force -ErrorAction Stop" in kill
    assert "Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue" not in kill


def test_a_survivor_stops_the_restart_before_anything_is_started():
    code = _code()
    stop = code.index("Stop-Process -Id $procId")
    recheck = code.index("$survivors = @(", stop)
    refuse = code.index("exit 5", recheck)
    start = code.index("Start-ScheduledTask -TaskName $TaskName")
    assert stop < recheck < refuse < start, "a service is started beside one that would not die"


def test_the_refusal_says_why_and_what_to_do():
    kill = _step(2)
    assert "Windows said" in kill, "the refusal hides Windows' own reason"
    assert "IsInRole" in kill and "Run as administrator" in kill
    assert "taskkill /PID" in kill, "an Administrator is not told how to end it by hand"
    assert "Nothing was started" in kill


def test_a_respawn_is_named_not_mistaken_for_a_restart():
    code = _code()
    respawn = code.index("exit 6")
    assert code.index("$survivors = @(") < respawn < code.index("Start-ScheduledTask -TaskName $TaskName")
    assert "Show-PortHolder $Port" in _step(2)


def test_the_start_time_comes_from_cim_not_get_process():
    kill = _step(2)
    assert "CreationDate" in kill
    assert "$p.StartTime" not in kill, "Get-Process cannot read another account's start time"


def test_both_supervisors_are_stopped_where_both_exist():
    step1 = _step(1)
    assert "Stop-ScheduledTask" in step1 and "Stop-Service" in step1
    assert "} elseif ($svc) {" not in step1, "the task OR the service is stopped, never both"


def test_the_one_that_was_serving_is_the_one_started():
    step3 = _step(3)
    assert "$svcWasRunning" in step3
    assert "$svcWasRunning = $true" in _step(1)


def test_still_stale_names_the_holder_instead_of_sending_the_reader_to_look():
    code = _code()
    at = code.index("STILL STALE")
    tail = code[at:code.index("exit 1", at)]
    assert "Show-PortHolder $Port" in tail
    assert "Get-Process" not in tail


def test_the_script_is_still_ascii_only():
    assert all(b < 128 for b in _PATH.read_bytes())
