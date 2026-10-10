<#
.SYNOPSIS
    Register the 5-minute BrightHR -> InVentry presence sync as a scheduled task.

.DESCRIPTION
    Without this, InVentry's on-site register is only as current as the last
    time somebody clicked the portal button - and the push refuses snapshots
    older than BLIP_MAX_STALE_MINUTES (15 by default), so a manual click gives
    a quarter of an hour of usefulness and then goes stale. A fire roll call
    needs the job.

    Defaults to DRY RUN, which logs what it would do and writes nothing to
    InVentry. Re-run with -Apply once a few dry-run cycles look right.

    Run elevated. Idempotent: an existing task of the same name is replaced.
    The registered task is read back and checked, because a task that registers
    cleanly can still be one that never fires.

.EXAMPLE
    # Dry run every 5 minutes - the safe first deployment
    .\install_presence_task.ps1

.EXAMPLE
    # Live, under a service account
    .\install_presence_task.ps1 -Apply -User "SDI\svc_brighthr" -Password (Read-Host -AsSecureString)
#>
[CmdletBinding()]
param(
    [string]$TaskName = "BrightHR-InVentry Presence Sync",
    [int]$IntervalMinutes = 5,
    [switch]$Apply,
    [string]$User,
    [System.Security.SecureString]$Password,
    [string]$Python,
    [string]$BackendDir = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$runner = Join-Path $BackendDir "deploy\run_presence_sync.ps1"
if (-not (Test-Path $runner)) { throw "run_presence_sync.ps1 not found at $runner" }
if (-not (Test-Path (Join-Path $BackendDir ".env"))) {
    throw @"
No .env in $BackendDir.
The task would start and abort on every cycle. Two likely causes:
  * this is the wrong checkout - the HR pipeline and its .env may live in a
    different worktree (git worktree list)
  * .env is deliberately not in git, so a fresh checkout has none. Copy it
    from a working machine, then run deploy\setup_inventry_host.ps1.
"@
}

# ── The interpreter ──────────────────────────────────────────────────────
# Resolved here, not left to the runner, because a task running as SYSTEM has
# no user PATH and no venv activation. Baking an absolute path into the task
# argument is what makes it work under SYSTEM at 3am.
if (-not $Python) {
    $repoRoot = Split-Path $BackendDir -Parent
    $Python = @(
        (Join-Path $BackendDir ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot  ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot  "venv\Scripts\python.exe")
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Python) {
        $onPath = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($onPath) {
            $Python = $onPath.Source
            Write-Host "Using the python.exe on your PATH: $Python" -ForegroundColor Yellow
            Write-Host "  If that is a per-user install, SYSTEM may not be able to run it." -ForegroundColor Yellow
        }
    }
}
if (-not $Python) {
    throw "No Python interpreter found in $BackendDir\.venv, the repository root, or PATH. Pass -Python <path to python.exe>."
}
Write-Host "Interpreter: $Python"

# Can that interpreter import what the job needs AS THE TASK WILL RUN IT?
# A package installed with a plain "pip install" by a non-admin user lands in
# that user's AppData site-packages. It imports fine when you test by hand and
# is invisible to SYSTEM, so every scheduled cycle dies on "import requests".
# -s tells Python to ignore the user site-packages: the same view SYSTEM gets,
# reproduced while you are still logged in as yourself.
& $Python -s -c "import requests, dotenv" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw @"
$Python cannot import requests and python-dotenv without your personal
site-packages - so it will fail every cycle when the task runs as SYSTEM.
(They are probably installed under C:\Users\<you>\AppData\Roaming\Python.)

The clean fix is a virtual environment inside the checkout, which this script
then finds and uses automatically:

  cd $BackendDir
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install requests python-dotenv

Then re-run this installer.
"@
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`" -Python `"$Python`""
if ($Apply) {
    Write-Warning "LIVE MODE: this task will sign staff in and out on the reception system."
    $arguments += " -Apply"
} else {
    Write-Host "Dry-run mode: the task will log intended changes only." -ForegroundColor Yellow
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $BackendDir

# ── Trigger ──────────────────────────────────────────────────────────────
# A -Once trigger with -RepetitionInterval but no -RepetitionDuration is the
# classic way to register a task that runs exactly once and then sits there
# looking healthy on older Windows: the repetition has no window to repeat
# within. So a duration is always given.
#
# NOT [TimeSpan]::MaxValue, which an earlier version of this script used.
# New-ScheduledTaskTrigger accepts it, and then on Windows 10 / Server 2016 and
# later Register-ScheduledTask rejects it - "The task XML contains a value which
# is incorrectly formatted or out of range ... Duration:P99999999DT23H59M59S".
# The failure surfaces at registration, after the trigger was built, so a
# try/catch around the trigger never sees it and the install simply stops.
# Ten years is valid on every version and, for a five-minute job, indefinite.
#
# The start boundary is a minute out rather than "now", so the first fire is a
# scheduled one instead of a missed one that -StartWhenAvailable has to recover.
$interval = New-TimeSpan -Minutes $IntervalMinutes
$start = (Get-Date).AddMinutes(1)
$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval $interval -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

# ── Who it runs as ───────────────────────────────────────────────────────
# A principal object, not the -User/-RunLevel shorthand: SYSTEM needs the
# ServiceAccount logon type, and a named account with no password needs S4U to
# run while nobody is logged on. Getting this wrong is the other common way a
# task refuses to start - it registers, then fails with 0x41... at run time.
if ($User -and $Password) {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password))
    $principal = $null   # Register-ScheduledTask takes User/Password directly.
} elseif ($User) {
    Write-Host "No password given for $User - registering with S4U so it runs while logged off." -ForegroundColor Yellow
    Write-Host "  That account needs the 'Log on as a batch job' right." -ForegroundColor DarkGray
    $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Highest
} else {
    # A dedicated service account is preferable to SYSTEM: the InVentry call and
    # any shares can then be granted narrowly and audited.
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    Write-Host "Running as SYSTEM. Note SYSTEM has no user drive mappings - keep HR_OUTPUT_DIR on a UNC path." -ForegroundColor Yellow
}

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Replacing existing task '$TaskName'"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$register = @{
    TaskName    = $TaskName
    Action      = $action
    Trigger     = $trigger
    Settings    = $settings
    Description = "Queries BrightHR Blip and pushes the on-site list into InVentry via the Partner API, for the on-site register and fire roll call."
}
if ($principal) { $register.Principal = $principal }
else            { $register.User = $User; $register.Password = $plain; $register.RunLevel = "Highest" }

Register-ScheduledTask @register | Out-Null

# ── Read it back ─────────────────────────────────────────────────────────
# Registration succeeding is not the same as the schedule being right.
$live = Get-ScheduledTask -TaskName $TaskName
$rep = $live.Triggers[0].Repetition
Write-Host ""
if ($rep.Interval) {
    Write-Host "Repetition confirmed: every $($rep.Interval), duration $(if ($rep.Duration) { $rep.Duration } else { 'indefinite' })" -ForegroundColor Green
} else {
    Write-Host "WARNING: the registered task has no repetition interval - it will run once only." -ForegroundColor Red
    Write-Host "         Fix it in Task Scheduler: the trigger's 'Repeat task every' box." -ForegroundColor Red
}

Write-Host "Registered '$TaskName' - every $IntervalMinutes minute(s), $(if ($Apply) {'LIVE'} else {'dry run'}), first run $($start.ToString('HH:mm'))." -ForegroundColor Green
Write-Host "  Start now   : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Last result : (Get-ScheduledTaskInfo -TaskName '$TaskName') | Select LastRunTime,LastTaskResult,NextRunTime"
Write-Host "                0 ok, 2 partial, 1 aborted, 0x41301 still running, 0x41303 never run"
Write-Host "  Run log     : C:\SDIIntelligence\hr\snapshots\presence_sync.log   <- read this first when a run does nothing"
Write-Host "  Pipeline log: <HR_SNAPSHOT_DIR>\hr_pipeline.log"
Write-Host "  Status      : <HR_SNAPSHOT_DIR>\hr_status.json  (onsite_push section)"
