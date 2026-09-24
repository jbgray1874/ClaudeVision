r"""The runner can be restarted by one command, and the page says which box runs what.

James Gray, 18 September 2026: "what are the stop and restart commands for the runner."

THE HONEST ANSWER THAT DAY WAS: THERE AREN'T ANY. `restart-service.ps1` has existed for the
SERVICE since the afternoon a restart failed to restart anything. The RUNNER -- the process
that actually costs jobs -- had nothing. Stopping it was a five-line PowerShell incantation
printed inside a `Write-Host` in `start-runner.ps1`, to be copied out of a terminal by hand.

WHAT THAT COST, THE SAME DAY. Job 401912-02 was run three times in twenty minutes. Every run
printed

    [build] engine source: 2314342 +local edits

while the branch had moved four commits ahead -- one of them the fix for the very crash that
ended each run. The pull had been done. The runner had never been restarted, so the pull
could not reach the process: a running Python holds the code it imported at start-up and goes
on holding it all day. Three identical tracebacks, nothing filed.

AND THE DISTINCTION UNDERNEATH IT. The SERVICE queues jobs; the RUNNER costs them. They are
different processes, usually on different machines, and only one of them runs the engine. A
pull on the service box changes nothing about how a job is priced. Every box has a
`C:\ClaudeVision` and an identical prompt, so nothing on screen tells them apart -- which is
why each script refuses to act on the wrong machine rather than reporting a success that
happened somewhere else.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PATH = _ROOT / "tools" / "start" / "restart-runner.ps1"
_PORTAL = _ROOT / "sdi-intelligence-backend" / "sdi-intelligence-portal.html"


@pytest.fixture(scope="module")
def script() -> str:
    assert _PATH.exists(), "there is no restart-runner.ps1 -- that was the whole finding"
    return _PATH.read_text(encoding="utf-8")


def _code(text: str) -> str:
    """The script with its prose blanked, length-preserved so offsets still mean order.

    Six tests in this suite have matched commentary ABOUT a thing instead of the thing.
    """
    without_header = re.sub(r"<#.*?#>", lambda m: " " * len(m.group(0)), text, flags=re.S)
    return "\n".join(
        (" " * len(ln)) if ln.lstrip().startswith("#") else ln
        for ln in without_header.split("\n"))


# ── it exists and Windows PowerShell 5.1 can read it ────────────────────────────────

def test_the_script_is_ascii_only(script):
    """Windows PowerShell 5.1 reads a .ps1 in the system codepage unless it carries a BOM,
    so one em dash arrives as three bytes of nonsense, terminates a string early, and throws
    a parse error pointing thirty lines from the real one. Every script in this folder is
    ASCII for that reason and this one is no exception."""
    raw = _PATH.read_bytes()
    assert all(b < 128 for b in raw), "non-ASCII bytes will break this under PowerShell 5.1"


def test_it_does_not_resolve_its_root_in_a_parameter_default(script):
    """$PSScriptRoot is EMPTY inside param() under `powershell -File`, so "$PSScriptRoot\\..\\.."
    becomes a root-relative path and resolves to C:\\. Three scripts here carried that line;
    two survived only because nobody had typed them the other way yet."""
    params = script[script.index("param("):script.index(")", script.index("param("))]
    assert "PSScriptRoot" not in params


# ── stopping actually stops ──────────────────────────────────────────────────────────

def test_the_task_alone_is_not_treated_as_a_stop(script):
    """The task's action is powershell.exe, which starts python as a CHILD. When the wrapper
    goes the child can be left running -- which is exactly why 'Stop-ScheduledTask;
    Start-ScheduledTask' can restart nothing at all."""
    code = _code(script)
    assert "Stop-ScheduledTask" in code
    assert "Stop-Process" in code
    assert code.index("Stop-ScheduledTask") < code.index("Stop-Process"), \
        "the processes must be ended AFTER the task, or the task restarts them"


def test_it_ends_every_runner_process_not_just_one(script):
    """One runner is TWO processes: a virtualenv python.exe is a launcher that starts the
    base interpreter as a child, with an identical command line."""
    code = _code(script)
    assert "sdi_estimate_runner" in code
    assert "foreach" in code.lower(), "a single Stop-Process leaves the other half running"


def test_a_process_is_named_before_it_is_killed(script):
    """A pid and a start time is what tells you afterwards whether you stopped the thing you
    meant to."""
    code = _code(script)
    at = code.index("Stop-Process")
    assert "ProcessId" in code[max(0, at - 700):at]


# ── it refuses to act on the wrong machine ───────────────────────────────────────────

def test_it_refuses_where_there_is_no_runner(script):
    """Run on the service box it would stop nothing, start nothing and report success -- and
    the reader would believe the runner had been restarted."""
    code = _code(script)
    assert "sdi_estimate_runner.py" in code
    guard = code[:code.index("# -- 1.") if "# -- 1." in code else len(code)]
    assert "exit 2" in code
    assert "Nothing has been stopped" in code


def test_the_refusal_explains_which_machine_the_runner_is(script):
    assert "SOLIDWORKS" in script and "logged in" in script


# ── a pull never eats somebody's work ────────────────────────────────────────────────

def test_a_dirty_tree_stops_the_pull_rather_than_being_worked_around(script):
    """Local edits are somebody's work. Losing an afternoon of them to a convenience flag is
    worse than the afternoon this script saves -- so it will not merge over, stash or discard
    them, it says what is uncommitted and stops."""
    code = _code(script)
    assert "--porcelain" in code
    assert "exit 4" in code
    for forbidden in ("git stash", "checkout --", "reset --hard", "clean -fd"):
        assert forbidden not in code, f"the script does something destructive: {forbidden}"


def test_the_pull_happens_before_anything_is_stopped(script):
    """A pull that fails must not read as a failed restart, and a runner must never be
    restarted onto a half-updated checkout."""
    code = _code(script)
    assert code.index("pull --ff-only") < code.index("Stop-ScheduledTask")


def test_pulling_is_opt_in(script):
    """This script's job is to restart. A pull that happens by surprise is how a tree gets
    updated at a moment nobody chose."""
    assert "[switch] $Pull" in script


# ── and it says what will now run ────────────────────────────────────────────────────

def test_it_reports_the_commit_the_engine_will_run(script):
    """'It restarted' and 'it is running the code you meant' are different claims and only
    the second one matters. This is the line that would have ended 401912-02's afternoon on
    the first run instead of the fourth."""
    code = _code(script)
    assert "rev-parse" in code
    assert code.index("Start-ScheduledTask") < code.index("rev-parse")


def test_it_shouts_when_the_checkout_is_still_behind(script):
    code = _code(script)
    assert "rev-list" in code and "HEAD..@{u}" in code
    assert "BEHIND" in code


def test_it_notices_when_the_runner_did_not_come_back(script):
    """Stopped and not restarted is the worst outcome of a restart command, and it must not
    be reported as success."""
    code = _code(script)
    assert "NO RUNNER IS RUNNING" in code
    assert "exit 6" in code


def test_cleaning_the_bytecode_caches_is_opt_in_and_says_so(script):
    """A command that quietly deletes things is a command people stop trusting."""
    assert "[switch] $Clean" in script
    code = _code(script)
    assert "__pycache__" in code
    assert "removed" in code.lower()


def test_git_absent_is_not_a_crash(script):
    """SDI-APP01 has no git, and under $ErrorActionPreference = 'Stop' a bare `& git` is a
    CommandNotFoundException BEFORE the redirect can catch it."""
    code = _code(script)
    assert "Get-Command git" in code


# ── the page says which box runs what ────────────────────────────────────────────────

@pytest.fixture(scope="module")
def portal() -> str:
    return _PORTAL.read_text(encoding="utf-8")


def test_the_tools_page_names_all_three_deployments_and_the_runner(portal):
    tools = portal[portal.index('<section class="view" id="tools">'):]
    tools = tools[:tools.index("</section>")]
    for addr in ("localhost:8072", "localhost:8071", "10.0.0.5:8071"):
        assert addr in tools, f"the tools page does not say how {addr} is run"
    assert "SDI-APP01" in tools
    assert "restart-runner.ps1" in tools


def test_the_page_states_the_distinction_that_cost_the_afternoon(portal):
    """A page that lists commands without saying which box changes a PRICE is a page that
    lets the same mistake happen again."""
    tools = portal[portal.index('<section class="view" id="tools">'):]
    tools = tools[:tools.index("</section>")]
    assert "service queues jobs" in tools.lower()
    assert "runner costs them" in tools.lower()
    assert "restarted" in tools


def test_the_page_gives_the_main_server_its_own_route(portal):
    """SDI-APP01 has no git, so `git pull` is not an instruction that means anything there.
    A page that implied it would send somebody to a prompt that cannot do what they want."""
    tools = portal[portal.index('<section class="view" id="tools">'):]
    tools = tools[:tools.index("</section>")]
    assert "push-to-server.ps1" in tools
    row = tools[tools.index("10.0.0.5:8071"):]
    assert "push-to-server.ps1" in row[:1200]


def test_the_page_tells_the_reader_what_a_good_run_looks_like(portal):
    tools = portal[portal.index('<section class="view" id="tools">'):]
    tools = tools[:tools.index("</section>")]
    assert "+local edits" in tools
    assert "[rates]" in tools


def test_the_page_is_still_one_well_formed_document(portal):
    import html.parser

    class _P(html.parser.HTMLParser):
        pass
    _P().feed(portal)


# ── and the service has a stop, on whichever supervisor the machine uses ─────────────
#
# Found while answering "are the stop and restart commands on that page now for the laptop
# and the server": there was no STOP for a service at all -- only start and restart -- and
# `restart-service.ps1` knew only about the laptop's scheduled task. SDI-APP01 runs the
# portal as an NSSM service. On that machine the script would find no task, KILL WHATEVER
# WAS LISTENING ON 8071, then print "start it yourself: install-service-task.ps1" and exit 1:
# the intranet stopped, on the production box, with the remedy naming a mechanism that
# machine does not use.

_SVC = (_ROOT / "tools" / "start" / "restart-service.ps1").read_text(encoding="utf-8")


def test_the_service_script_is_still_ascii_only():
    raw = (_ROOT / "tools" / "start" / "restart-service.ps1").read_bytes()
    assert all(b < 128 for b in raw)


def test_a_service_can_be_stopped_and_left_stopped():
    assert "[switch] $StopOnly" in _SVC
    code = _code(_SVC)
    assert code.index("Stop-Process") < code.index("if ($StopOnly)"), \
        "-StopOnly must stop the orphan too, not just the supervisor"


def test_the_nssm_service_is_found_where_there_is_no_task():
    code = _code(_SVC)
    assert "Get-Service" in code
    assert "SDIIntelligence" in _SVC


def test_the_supervisor_is_stopped_before_the_port_is_killed():
    """NSSM RESTARTS WHAT YOU KILL. Ending the process while the service still supervises it
    brings the OLD code straight back, the health check passes, and the restart reports
    success having changed nothing."""
    code = _code(_SVC)
    assert code.index("Stop-Service") < code.index("Stop-Process")


def test_the_supervisor_is_resolved_once_and_reused():
    """Asking again after the kill could get a different answer and restart the wrong thing."""
    code = _code(_SVC)
    assert code.index("$svc  = Get-Service") < code.index("Stop-Service")
    assert code.index("$svc  = Get-Service") < code.index("Start-Service")


def test_a_service_it_stopped_is_a_service_it_starts():
    code = _code(_SVC)
    assert "Start-Service" in code


def test_an_unsupervised_service_is_told_the_truth_rather_than_the_laptops_remedy():
    """A hand-started window has no supervisor to restart. Naming install-service-task.ps1
    there sends somebody to install a scheduled task they did not want."""
    # Sliced from the RAW script: the section markers are comments, which _code() blanks.
    tail = _code(_SVC)[_SVC.index("# -- 3. START IT AGAIN"):]
    assert "start-service.ps1" in tail
    assert "install-service-task.ps1" not in tail, \
        "the laptop's remedy is still being offered to a machine that does not use it"


def test_the_page_carries_a_stop_and_a_restart_for_every_box(portal):
    tools = portal[portal.index('<section class="view" id="tools">'):]
    tools = tools[:tools.index("<h2>Entry Points</h2>")]
    flat = tools.replace("&nbsp;", " ")
    for cmd in ("restart-service.ps1 -Port 8072 -StopOnly",
                "restart-service.ps1 -Port 8072",
                "restart-service.ps1 -Port 8071 -StopOnly",
                "restart-service.ps1 -Port 8071",
                "restart-runner.ps1 -StopOnly",
                "restart-runner.ps1 -Pull"):
        assert cmd in flat, f"the page has no command: {cmd}"


def test_the_page_says_the_server_is_nssm_and_the_laptop_is_a_task(portal):
    tools = portal[portal.index('<section class="view" id="tools">'):]
    tools = tools[:tools.index("<h2>Entry Points</h2>")]
    assert "NSSM" in tools
    assert "SDIIntelligence" in tools
    assert "SDI Intelligence Service" in tools


def test_the_page_says_pushing_does_not_restart(portal):
    """The step after push-to-server is the one that was missing, and it is the step that
    makes the copy take effect."""
    tools = portal[portal.index('<section class="view" id="tools">'):]
    tools = tools[:tools.index("<h2>Entry Points</h2>")]
    assert "does not restart" in tools.lower()
    at = tools.lower().index("does not restart")
    assert "restart-service.ps1 -Port 8071" in tools[at:at + 900]


# ── a kill is confirmed, not assumed (23 Sep 2026) ────────────────────────────────────
#
# The script printed "ending pid 41104" and the heartbeat on 8071 went on advertising pid
# 41104, build b4b4afa, started 19:21 the day before. It searched python.exe only while the
# task runs pythonw.exe; it never checked the kill; and step 6 counted the survivor as the
# restarted runner.

def test_the_kill_step_finds_pythonw_too(script):
    code = _code(script)
    kill = code[code.index("function Get-RunnerProcs"):code.index("if ($Clean)")]
    assert "pythonw.exe" in kill, "the windowless runner the task starts is never ended"


def test_a_survivor_stops_the_restart(script):
    code = _code(script)
    stop = code.index("Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop")
    recheck = code.index("$left = Get-RunnerProcs", stop)
    refuse = code.index("exit 7", recheck)
    start = code.index("Start-ScheduledTask -TaskName $TaskName")
    assert stop < recheck < refuse < start, "a runner is started beside one that would not die"


def test_only_a_runner_born_after_the_restart_counts(script):
    code = _code(script)
    wait = code[code.index("while ($waited -lt 45)"):code.index("NO RUNNER IS RUNNING")]
    assert "$restartAt" in wait, "the old runner satisfies the 'did it come back' check"


def test_a_cim_creation_date_is_already_a_datetime(script):
    """Get-CimInstance returns CreationDate as a DateTime; the WMI-string converter threw on
    it, so the 'born after the restart' check never passed and a healthy runner was reported
    missing after 45 seconds."""
    code = _code(script)
    fn = code[code.index("function Get-Started"):code.index("$procs = Get-RunnerProcs")]
    assert "-is [DateTime]" in fn


def test_a_refused_task_install_is_not_reported_as_installed():
    """Register-ScheduledTask 'Access is denied' is non-terminating: the installer printed
    'Installed ... server 8071' and started the old task, still pointed at 8072."""
    text = (_ROOT / "tools" / "start" / "install-runner-task.ps1").read_text(encoding="utf-8-sig")
    code = _code(text)
    reg = [m.start() for m in re.finditer(r"Register-ScheduledTask -TaskName", code)]
    assert reg and all("-ErrorAction Stop" in code[r:r + 250] for r in reg)
    refuse = code.index("exit 8")
    assert refuse < code.index('Write-Host "Installed scheduled task')
    assert refuse < code.index("Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop")


# ── a launcher and its child are one runner; the service is asked, not the reader ────

def test_a_venv_launcher_and_its_child_are_reported_as_one_runner(script):
    """24 Sep 2026: pythonw 61184 and 53776, both 11:08:00, were read as two runners. They
    were the venv launcher and the interpreter it starts."""
    code = _code(script)
    assert "ParentProcessId" in code
    assert "$roots.Count -gt 1" in code and "exit 8" in code


def test_the_restart_ends_by_asking_the_service(script):
    code = _code(script)
    ask = code.index("/api/estimate/runners")
    assert ask > code.index("Start-ScheduledTask -TaskName")
    for check in ("process_count -ne 1", "$mine.conflict", "+local edits", "StartsWith($headSha)"):
        assert check in code, check
    assert "exit 9" in code and "exit 10" in code and "PASS" in code


def test_the_service_can_be_on_another_machine(script):
    params = script[script.index("param("):script.index("\n)", script.index("param("))]
    assert "$Service" in params and "SDI_SERVICE_URL" in _code(script)
