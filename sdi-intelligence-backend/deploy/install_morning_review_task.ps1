<#
.SYNOPSIS
    Register the weekday morning review email (SDI Intelligence AM CRM).

.DESCRIPTION
    Runs morning_review.py --send at 07:50 Monday to Friday, so the review is
    in Nick's and James's inboxes before 8am. It reads the sandbox tracker with
    an app-only token (Sites.Selected, sandbox site only), counts what is
    overdue or inconsistent, and emails SDI_REVIEW_TO through the service's
    existing SMTP settings. Read-only: it never writes to the tracker.

    Run elevated, on SDI-App01. Idempotent: an existing task of the same name
    is replaced. Output of every run goes to logs\morning_review.log.

.EXAMPLE
    .\install_morning_review_task.ps1
    Start-ScheduledTask -TaskName 'SDI AM CRM Morning Review'   # send one now
#>
[CmdletBinding()]
param(
    [string]$TaskName = "SDI AM CRM Morning Review",
    [string]$At = "07:50",
    [string]$BackendDir = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$python = Join-Path $BackendDir ".venv\Scripts\python.exe"
$script = Join-Path $BackendDir "morning_review.py"
if (-not (Test-Path $python)) { throw "Service virtualenv not found at $python" }
if (-not (Test-Path $script)) { throw "morning_review.py not found at $script" }
if (-not (Select-String -Path (Join-Path $BackendDir ".env") -Pattern '^SDI_REVIEW_TO=.+@' -Quiet)) {
    throw "SDI_REVIEW_TO is not set in .env - the task would send to nobody."
}

$logDir = Join-Path $BackendDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "morning_review.log"

$cmd = "/c echo ==== %DATE% %TIME% >> `"$log`" && `"$python`" `"$script`" --send --weekdays-only >> `"$log`" 2>&1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmd -WorkingDirectory $BackendDir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -StartWhenAvailable `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Replacing existing task '$TaskName'"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -User "SYSTEM" -RunLevel Highest `
    -Description "Emails the SDI Intelligence AM CRM morning review (sandbox tracker, read-only) to SDI_REVIEW_TO." | Out-Null

Write-Host ""
Write-Host "Registered '$TaskName' - weekdays at $At." -ForegroundColor Green
Write-Host "  Send one now : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Last result  : (Get-ScheduledTaskInfo -TaskName '$TaskName').LastTaskResult   # 0 = sent"
Write-Host "  Log          : Get-Content '$log' -Tail 40"
