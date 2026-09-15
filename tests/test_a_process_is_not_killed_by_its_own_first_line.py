"""The runner reported that it had started, and died on the first line it logged.

    python.exe : At C:\\ClaudeVision\\tools\\start\\start-runner.ps1:177 char:1
    + & $python $runner ...
        + FullyQualifiedErrorId : NativeCommandError

In Windows PowerShell 5.1 a native command's STDERR is written into the error stream as a
NativeCommandError record, and under `$ErrorActionPreference = "Stop"` that record is
TERMINATING. Python's logging writes to stderr by default. So a script that sets Stop at the
top — which every script here does, and should, because it is what makes a failed step stop
the run — kills the long-running process it exists to start, at the moment that process
begins to talk.

IT IS THE WORST SHAPE OF FAILURE. The window says "found the service at http://localhost:8072"
and "serving", both in green, and then throws. It reads as a program that started and crashed
for its own reasons; the cause is the starter treating normal output as a fault. The service
hit this first (logging the service is what stopped it running) and start-service.ps1 has
carried the fix since. start-runner.ps1 never got it — the same bug, in the same shell, one
file over, found three weeks later by an estimator who could not run a job.

So this is asked of the CLASS, not of the line. Every script that launches a long-running
Python process must drop the preference around that one statement, whichever script it is and
whenever it is written — including the next one.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START = ROOT / "tools" / "start"

# `& $python $app`, `& $python $runner` — a native launch of the interpreter with a script.
_LAUNCH = re.compile(r"^\s*&\s*\$python\s+\$\w+", re.M)
_PREF = re.compile(r'\$ErrorActionPreference\s*=\s*"(\w+)"')


def _scripts():
    return sorted(p for p in START.glob("*.ps1"))


def test_there_are_start_scripts_to_check():
    """A glob that matches nothing passes every test in this file silently."""
    assert _scripts(), "no PowerShell start scripts found — this suite is not checking anything"


def test_every_python_launch_runs_with_stderr_treated_as_output():
    """For each launch site, the preference IN FORCE at that point must not be Stop.

    Read positionally rather than by name, so a script that sets Stop, drops it for the
    launch and restores it afterwards passes, and one that merely mentions "Continue"
    somewhere else does not.
    """
    checked = 0
    for script in _scripts():
        src = script.read_text(encoding="utf-8", errors="replace")
        for launch in _LAUNCH.finditer(src):
            checked += 1
            before = [m.group(1) for m in _PREF.finditer(src[:launch.start()])]
            in_force = before[-1] if before else "Continue"
            assert in_force != "Stop", (
                f"{script.name}: `{launch.group(0).strip()}` runs while "
                f'$ErrorActionPreference is "Stop". The first line this process writes to '
                f"stderr will be a terminating NativeCommandError and the process will be "
                f"killed — after the window has already said it started. Drop the preference "
                f"for this one statement and restore it in a finally, as start-service.ps1 "
                f"does.")
    assert checked >= 2, f"expected the service and the runner to be launched; found {checked}"


def test_the_preference_is_restored_rather_than_left_off():
    """Dropping it permanently would fix this and lose what Stop is for — a failed step
    after the process exits going unnoticed. Restored in a finally, so a crash still
    restores it."""
    for script in _scripts():
        src = script.read_text(encoding="utf-8", errors="replace")
        if not _LAUNCH.search(src):
            continue
        if '$ErrorActionPreference = "Continue"' not in src:
            continue
        assert "finally" in src, (
            f"{script.name}: drops $ErrorActionPreference for the launch and never restores "
            f"it in a finally")


def test_both_known_launchers_are_covered():
    """Named, because these two are the pair the defect has now been found in — the service
    in August, the runner in September, and nothing connected them at the time."""
    for name in ("start-service.ps1", "start-runner.ps1"):
        script = START / name
        assert script.is_file(), name
        src = script.read_text(encoding="utf-8", errors="replace")
        assert _LAUNCH.search(src), f"{name}: no `& $python $...` launch found"
        assert '$ErrorActionPreference = "Continue"' in src, name


def test_the_runner_says_why_rather_than_only_what():
    """A comment naming NativeCommandError is how the next person reading this file learns
    that green "serving" lines above a throw are not evidence the process ran."""
    src = (START / "start-runner.ps1").read_text(encoding="utf-8", errors="replace")
    assert "NativeCommandError" in src
    assert "stderr" in src.lower()
