<#
    Install the SDI Intelligence SERVICE as a Scheduled Task that starts itself
    and restarts itself.

        .\tools\start\install-service-task.ps1
        .\tools\start\install-service-task.ps1 -Port 8073
        .\tools\start\install-service-task.ps1 -Remove

    WHY THIS EXISTS, WHICH IS THE WHOLE POINT.

    The runner had a scheduled task keeping it alive. The service - the portal
    itself, the thing the browser talks to - had NOTHING. start-service.ps1 ends
    with `& $python $app` in the foreground of a console window, so the entire
    intranet site lived or died with one window somebody had to remember not to
    close. Close it, reboot, or let a Ctrl+C land in the wrong place and every
    page returns ERR_CONNECTION_REFUSED with nothing on the machine explaining
    why. There was no supervisor, no restart, no log, and no record.

    That is not a workflow anybody should have to run an intranet on, and it is
    the reason "is it up?" has been a question at all.

    WHY A SCHEDULED TASK AND NOT A WINDOWS SERVICE - the same reason as the
    runner, and it has already been learned the expensive way here. A Windows
    service runs as LocalSystem in session 0. LocalSystem has NO MAPPED DRIVES
    and no rights on the CAD share, so the service starts, reports itself
    healthy, and then fails on every estimate the moment it touches
    \\sdi-dc01\shareddata$. That is exactly what the NSSM service on 8071 did.
    -LogonType Interactive runs it as the logged-on user, with that user's
    credentials on the share.

    WHAT THIS FIXES AND WHAT IT DOES NOT. It stops a closed window, a crash or a
    reboot from taking the site down until somebody notices. It does NOT survive
    the machine being logged out or shut down - nothing can, for the same reason
    the runner cannot.

    IT WILL NOT FIGHT A SERVICE YOU STARTED YOURSELF. start-service.ps1 refuses
    a port that is already held (without -Force) and exits, so a sweep that finds
    the site already up does nothing at all.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [int]    $Port = 8072,
    [string] $Root = "",
    [string] $TaskName = "SDI Intelligence Service",
    [switch] $Remove
)

$ErrorActionPreference = "Stop"

# -- WHERE THIS SCRIPT IS, ASKED IN THE BODY AND NOT IN A PARAMETER DEFAULT ----------
# $PSScriptRoot is EMPTY inside param() under `powershell -File`, so "$PSScriptRoot\..\.."
# becomes "\..\.." - a ROOT-RELATIVE path - and resolves to C:\. Every script in this folder
# carried that bug; this one is written the right way from the start.
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

$starter = Join-Path $Root "tools\start\start-service.ps1"
if (-not (Test-Path $starter)) {
    throw ("$Root does not look like the ClaudeVision checkout - no " +
           "tools\start\start-service.ps1 under it. Pass -Root explicitly.")
}

if ($Remove) {
    # SAY WHAT THIS DOES BEFORE DOING IT. Unregistering a task terminates the instance the
    # scheduler is running, so -Remove takes the SITE DOWN, now, for everybody on it. The
    # runner's -Remove claimed the opposite and killed an estimate mid-run; this one does not
    # repeat that.
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "No scheduled task '$TaskName' to remove." -ForegroundColor Yellow
        Write-Host "A service started by hand in a console is a separate process, untouched."
        exit 0
    }
    if ($existing.State -eq "Running") {
        Write-Host "'$TaskName' is RUNNING RIGHT NOW." -ForegroundColor Yellow
        Write-Host "Removing it stops the service. Every page returns"
        Write-Host "ERR_CONNECTION_REFUSED until something starts it again, and any estimate"
        Write-Host "queued but not yet claimed is lost - the queue is held in memory."
        Write-Host ""
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Write-Host "Stopped it." -ForegroundColor Yellow
    }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    Write-Host "Nothing starts the service automatically now."
    exit 0
}

$backendPython = Join-Path $Root "sdi-intelligence-backend\.venv\Scripts\python.exe"
if (-not (Test-Path $backendPython)) { throw "No service virtualenv at $backendPython" }

# POWERSHELL RUNS THE STARTER, not python directly. The starter does three things a bare
# `python app.py` does not: it refuses a port already held, it resolves the git commit so
# /api/health and X-SDI-Commit tell the truth about which code is serving, and it sets
# SDI_PORT in the process that actually runs the app. Reimplementing those here would be a
# second copy to keep in step, and the first one to drift would be the one nobody is watching.
#
# -WindowStyle Hidden because this is the always-on site, not a console session. -Log makes it
# write to output\logs\service-<date>.log, which is the only record there will be.
$psExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$argline = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden " +
           "-File `"$starter`" -Port $Port -Log"

$action = New-ScheduledTaskAction -Execute $psExe -Argument $argline -WorkingDirectory $Root

# TWO TRIGGERS, for the reason set out in install-runner-task.ps1: AtLogOn brings it up with
# the desktop, and a five-minute sweep is what makes "up as long as the laptop is on" actually
# true. Windows' own restart handling gives up after three tries in an hour and does not fire
# at all on a clean exit; after either, an AtLogOn-only task is gone until the next reboot.
$triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
try {
    $sweep = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5)
    $sweep.Repetition.Duration = ""          # indefinite; some builds default to one day
    $triggers += $sweep
} catch {
    Write-Host "  note: could not add the 5-minute restart sweep ($($_.Exception.Message))." -ForegroundColor Yellow
    Write-Host "        the task still starts at logon and restarts on failure."
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

# INTERACTIVE, so the service runs as this user and therefore HAS this user's rights on
# \\sdi-dc01\shareddata$. LocalSystem is what broke the 8071 service.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

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
Write-Host "  site     http://localhost:$Port/estimating"
Write-Host "  runs as  $env:USERDOMAIN\$env:USERNAME (so it can read the CAD share)"
Write-Host "  starts   at logon, restarts on failure, checked every 5 minutes"
Write-Host "  log      $Root\output\logs\service-<date>.log"
Write-Host ""

Write-Host "Starting it now (the trigger alone would wait for the next logon)..." -ForegroundColor Cyan
try {
    Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    # Longer than the runner's 3s: uvicorn has to import the app before it listens, and
    # reporting "not up" while it is still starting would be its own false alarm.
    Start-Sleep -Seconds 8
    $state = (Get-ScheduledTask -TaskName $TaskName).State
    Write-Host "    task state: $state" -ForegroundColor Green

    # THE TASK RUNNING IS NOT THE SITE ANSWERING, and only one of those is what was asked
    # for. The task can be Running while the starter is on its way to exiting because the
    # port was held, or while python is failing an import. So ask the site.
    try {
        $health = Invoke-RestMethod "http://localhost:$Port/api/health" -TimeoutSec 5
        Write-Host "    site answering on $Port (commit $($health.commit))" -ForegroundColor Green
    } catch {
        # 401 means it IS answering and simply wants the key - that is a pass, not a failure.
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -eq 401) {
            Write-Host "    site answering on $Port (401 - key required, which is fine)" -ForegroundColor Green
        } else {
            Write-Host "    NOT answering on $Port yet." -ForegroundColor Yellow
            Write-Host "    Give it a few seconds and reload the page. If it stays down, the"
            Write-Host "    reason is in $Root\output\logs\service-<date>.log" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "    could not start it: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "    start it by hand:  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "This service QUEUES estimates. It does not run them - the runner does:" -ForegroundColor Yellow
Write-Host "    .\tools\start\install-runner-task.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "Stop it:      Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Restart it:   Stop-ScheduledTask -TaskName '$TaskName'; Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove it:    .\tools\start\install-service-task.ps1 -Remove"
