<#
.SYNOPSIS
    Register the weekday HR morning summary email (HRInventry Anywhere).

.DESCRIPTION
    Runs tools\hr_morning_summary.py --send at 08:45 Monday to Friday. It asks
    BrightHR who is clocked in, compares that with InVentry's fire list, and
    emails SDI_HR_MORNING_TO a summary: who is in, what needs attention
    (people missing from InVentry, forgotten clock-outs), the roll calls since
    the last summary, and a link to the app.

    Without -Update it changes nothing in BrightHR or InVentry. With -Update it
    first updates InVentry, exactly as the app's Update InVentry button does,
    with the same safety checks, and the email says what changed.

    Run elevated, on SDI-App01. Idempotent: an existing task of the same name
    is replaced. Output of every run goes to logs\hr_morning_summary.log, and
    each run shows in the app's History tab.

.EXAMPLE
    .\install_hr_morning_task.ps1
    Start-ScheduledTask -TaskName 'SDI HR Morning Summary'   # send one now
.EXAMPLE
    .\install_hr_morning_task.ps1 -Update      # also update InVentry at 08:45
#>
[CmdletBinding()]
param(
    [string]$TaskName = "SDI HR Morning Summary",
    [string]$At = "08:45",
    [switch]$Update,
    [switch]$EveryDay,
    [string]$BackendDir = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$elevated = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $elevated) {
    throw "This PowerShell window is not running as Administrator. Right-click Windows PowerShell -> Run as administrator, then run this again."
}

$python = Join-Path $BackendDir ".venv\Scripts\python.exe"
$script = Join-Path $BackendDir "tools\hr_morning_summary.py"
if (-not (Test-Path $python)) { throw "Service virtualenv not found at $python" }
if (-not (Test-Path $script)) { throw "tools\hr_morning_summary.py not found at $script - copy it to the server first." }
if (-not (Select-String -Path (Join-Path $BackendDir ".env") -Pattern '^SDI_HR_MORNING_TO=.+@' -Quiet)) {
    throw "SDI_HR_MORNING_TO is not set in .env - the task would send to nobody."
}

$logDir = Join-Path $BackendDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "hr_morning_summary.log"

$flags = "--send" + $(if ($Update) { " --update" } else { "" }) + $(if ($EveryDay) { "" } else { " --weekdays-only" })
$cmd = "/c echo ==== %DATE% %TIME% >> `"$log`" && `"$python`" `"$script`" $flags >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmd -WorkingDirectory $BackendDir
$trigger = if ($EveryDay) { New-ScheduledTaskTrigger -Daily -At $At } else {
    New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At }
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -StartWhenAvailable `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Replacing existing task '$TaskName'"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -User "SYSTEM" -RunLevel Highest `
    -Description "Emails the HRInventry Anywhere morning summary to SDI_HR_MORNING_TO." | Out-Null

# Read back: a task that registers cleanly can still be one that never fires.
$info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
$days = if ($EveryDay) { "every day" } else { "weekdays" }
$what = if ($Update) { "updates InVentry, then emails" } else { "checks only (changes nothing), then emails" }

Write-Host ""
Write-Host "Registered '$TaskName' - $days at $At; $what." -ForegroundColor Green
Write-Host "  Next run     : $($info.NextRunTime)"
Write-Host "  Send one now : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Last result  : (Get-ScheduledTaskInfo -TaskName '$TaskName').LastTaskResult   # 0 = sent"
Write-Host "  Log          : Get-Content '$log' -Tail 60"
