<#
    Install the SDI estimating runner as a Scheduled Task that starts itself and
    restarts itself.

        .\tools\start\install-runner-task.ps1
        .\tools\start\install-runner-task.ps1 -Remove

    WHY A SCHEDULED TASK AND NOT A WINDOWS SERVICE.

    This is the important part and it is easy to get wrong in a way that looks
    right for a week. The runner drives SOLIDWORKS and Excel through COM, and COM
    needs a licensed, INTERACTIVE desktop session. A normal Windows service runs
    in session 0 with no desktop, so it would install cleanly, start cleanly,
    report itself healthy, and then fail on every estimate the moment it tried to
    open SOLIDWORKS. NSSM would do the same thing. "Allow service to interact
    with desktop" has not worked properly since Windows Vista and does not work
    here.

    A Scheduled Task set to "run only when the user is logged on" runs in that
    user's real desktop session, which is the same place a hand-started runner
    runs. It survives the window being closed, starts at logon, and Windows
    restarts it if the process exits.

    WHAT THIS FIXES AND WHAT IT DOES NOT. It stops a closed window, a stray
    Ctrl+C or a crash from leaving the page saying "no runner connected" until
    somebody notices. It does NOT stop the machine being logged out, locked by a
    policy, or shut down - nothing can, because without a desktop session there
    is no SOLIDWORKS.

    The runner already refuses to start twice (an OS lock, released however the
    process dies), so the task and a hand-started window cannot fight: whichever
    is second says so and exits.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [string] $Root = "",
    # THE SAME TRAP AS start-runner.ps1 HAD. A hard-coded port bakes ONE answer into a task
    # that then runs unattended at every logon, so when the wrong service is the live one the
    # runner polls into silence for ever and the page says "no runner connected". SDI_PORT if
    # this window knows it, else 8072, which is what start-service.ps1 serves; pass -Server to
    # pin it to the installed Windows service on 8071 instead.
    [string] $Server   = ("http://localhost:" + $(if ($env:SDI_PORT) { $env:SDI_PORT } else { "8072" })),
    [string] $TaskName = "SDI Estimating Runner",
    [switch] $Remove
)

$ErrorActionPreference = "Stop"

# -- WHERE THIS SCRIPT IS, ASKED IN THE BODY AND NOT IN A PARAMETER DEFAULT ----------
#
# $PSScriptRoot is EMPTY inside param() under `powershell -File`, so "$PSScriptRoot\..\.."
# becomes "\..\.." - a ROOT-RELATIVE path - and Resolve-Path turns it into C:\. The script
# then looked for the virtualenv at C:\.venv\Scripts\python.exe and threw. It worked when
# invoked as .\tools\start\<script>.ps1 and failed under -File, which is a difference
# nobody should have to know about to start a runner.
#
# All three scripts in this folder carried the identical line. Two survived only because
# nobody had typed them the other way yet.
#
# Two fallbacks, then a refusal that names what it resolved to. A path silently one level
# wrong is exactly how this failed: the error named C:\.venv and nothing said why.
if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) {
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if (-not $here) {
        throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision explicitly."
    }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}

# AND CHECK IT IS THE ENGINE, not merely a folder that exists. C:\ exists.
if (-not (Test-Path (Join-Path $Root "tools\runner\sdi_estimate_runner.py"))) {
    throw ("$Root does not look like the ClaudeVision checkout - no " +
           "tools\runner\sdi_estimate_runner.py under it. Pass -Root explicitly if the " +
           "engine is somewhere else.")
}


if ($Remove) {
    # -Remove KILLS AN ESTIMATE IN PROGRESS, AND THIS SAID THE OPPOSITE.
    #
    # It claimed "any runner running right now keeps running until it stops", which is not
    # what happens: unregistering a task terminates the instance the scheduler is running,
    # and the runner is that instance. So -Remove ends the engine mid-estimate, the process
    # tree dies with no traceback, and the log simply stops in the middle of a job that was
    # going perfectly well. Somebody reading it afterwards sees a run that died for no
    # reason and goes looking for a crash that never happened. That cost an afternoon.
    #
    # So: say what it does BEFORE doing it, stop the task deliberately rather than as a side
    # effect, and name the run that was lost.
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "No scheduled task '$TaskName' to remove." -ForegroundColor Yellow
        Write-Host "A runner started by hand is a separate process and is untouched."
        exit 0
    }
    if ($existing.State -eq "Running") {
        Write-Host "'$TaskName' is RUNNING RIGHT NOW." -ForegroundColor Yellow
        Write-Host "Removing it ends that process. If it is part-way through an estimate,"
        Write-Host "that estimate is lost and nothing is filed - the engine is killed, so"
        Write-Host "the log simply stops mid-job."
        Write-Host ""
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Write-Host "Stopped it." -ForegroundColor Yellow
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    Write-Host "Nothing starts the runner automatically now. A runner you started by hand in"
    Write-Host "a console window is a SEPARATE process and is not affected by this."
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\pythonw.exe"    # windowless; falls back below
if (-not (Test-Path $python)) { $python = Join-Path $Root ".venv\Scripts\python.exe" }
$runner = Join-Path $Root "tools\runner\sdi_estimate_runner.py"

if (-not (Test-Path $python)) { throw "No engine virtualenv at $python" }
if (-not (Test-Path $runner)) { throw "No runner at $runner" }

# RUN AS THE LOGGED-ON USER, IN THEIR SESSION. -LogonType Interactive is the
# whole point: it is what gives the process a desktop, and therefore SOLIDWORKS.
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$runner`" --server `"$Server`"" -WorkingDirectory $Root

# TWO TRIGGERS, BECAUSE ONE OF THEM HAS A HOLE IN IT.
#
# AtLogOn starts the runner when the desktop session appears, which is the only
# moment SOLIDWORKS becomes possible. On its own it is not "up as long as the
# laptop is": Windows' own restart handling below gives up after three attempts
# in an hour, and it does not fire at all when the process exits with code 0. Once
# either of those happens the runner is gone until the next logon, which in
# practice means until the machine is next rebooted - days.
#
# So a second trigger sweeps every five minutes for ever. -MultipleInstances
# IgnoreNew makes that free when a runner is already up: the sweep is refused by
# the scheduler and nothing happens. When one is NOT up, it is back within five
# minutes without anybody noticing it went.
$triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
try {
    $sweep = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5)
    # Some Windows builds default the repetition to a fixed duration and quietly stop
    # after a day. Ask for indefinite explicitly; if the property is rejected, the
    # AtLogOn trigger alone still installs rather than the whole thing failing.
    $sweep.Repetition.Duration = ""
    $triggers += $sweep
} catch {
    Write-Host "  note: could not add the 5-minute restart sweep ($($_.Exception.Message))." -ForegroundColor Yellow
    Write-Host "        the task still starts at logon and restarts on failure."
}

# RestartInterval/RestartCount are what make this worth doing: if the process
# exits for any reason, Windows starts it again a minute later, up to three times
# an hour, without anybody watching. ExecutionTimeLimit 0 because an estimate can
# legitimately take an hour and a task that kills its own work is worse than no
# task at all.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

# The sweep trigger is the part most likely to be rejected by an older build's task XML
# validation. If it is, install WITHOUT it rather than failing the whole installation and
# leaving the machine with no task at all - a runner that starts at logon is far better than
# none, and the message says which of the two got installed.
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Force | Out-Null
} catch {
    Write-Host "  note: Windows refused the 5-minute sweep ($($_.Exception.Message))." -ForegroundColor Yellow
    Write-Host "        installing with the logon trigger only."
    $triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Force | Out-Null
}

Write-Host "Installed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  python   $python"
Write-Host "  server   $Server"
Write-Host "  starts   at logon for $env:USERNAME, in that session (SOLIDWORKS needs one)"
Write-Host "  restarts every minute if it exits, three times an hour"
Write-Host "  and is checked every 5 minutes after that, so it comes back on its own"
Write-Host ""

# START IT, DO NOT MERELY OFFER TO. The trigger is AtLogOn, so registering the task left
# nothing running until the next logon -- and this script said so in one Cyan line among
# fifteen, which is not the same as it happening. Somebody installed the task, saw a page
# still reporting "no runner connected", and had no reason to connect the two.
Write-Host "Starting it now (the trigger alone would wait for the next logon)..." -ForegroundColor Cyan
try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Start-Sleep -Seconds 3
    $info  = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
    $state = (Get-ScheduledTask -TaskName $TaskName).State
    Write-Host "    task state: $state" -ForegroundColor Green

    # STATE IS THE ANSWER; LastTaskResult IS NOT. Running means it worked, whatever code the
    # scheduler last recorded - and the codes it records on a SUCCESSFUL install look alarming.
    # 0x800710E0 is "refused, an instance is already running", which is -MultipleInstances
    # IgnoreNew doing precisely its job when the sweep trigger and this manual start coincide.
    # Printing that in yellow under a task that is up reads as a failure and sends somebody
    # looking for a problem that is not there.
    if ($state -ne "Running") {
        $why = switch ($info.LastTaskResult) {
            0          { "the runner started and then exited - see the log below" }
            267011     { "it has not run yet" }
            267014     { "the last run was stopped by hand" }
            2147942402 { "file not found - check the python path above" }
            2147943645 { "the service cannot be started in its current state" }
            2147946720 { "an instance was already running, so this start was refused" }
            default    { "code $($info.LastTaskResult)" }
        }
        Write-Host "    NOT running: $why" -ForegroundColor Yellow
        Write-Host "    try:  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
    }
} catch {
    Write-Host "    could not start it: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    start it by hand:  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
}
Write-Host ""
Write-Host "It writes everything it says to:" -ForegroundColor Cyan
Write-Host "    $Root\output\logs\runner-<date>.log"
Write-Host "so a death leaves a record rather than a closed window."
Write-Host ""
Write-Host "Stop it:      Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "Remove it:    .\tools\start\install-runner-task.ps1 -Remove"
