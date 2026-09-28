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
    [string]$BackendDir = (Resolve-Path "$PSScriptRoot\..").Path
)

$ErrorActionPreference = "Stop"

$runner = Join-Path $BackendDir "deploy\run_presence_sync.ps1"
if (-not (Test-Path $runner)) { throw "run_presence_sync.ps1 not found at $runner" }
if (-not (Test-Path (Join-Path $BackendDir ".env"))) {
    throw "No .env in $BackendDir. Run deploy\setup_inventry_host.ps1 first."
}

$arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$runner`""
if ($Apply) {
    Write-Warning "LIVE MODE: this task will sign staff in and out on the reception system."
    $arguments += " -Apply"
} else {
    Write-Host "Dry-run mode: the task will log intended changes only." -ForegroundColor Yellow
}

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $BackendDir

# Repeat indefinitely from registration.
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5)

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
    RunLevel    = "Highest"
}

if ($User) {
    # A dedicated service account is preferable to SYSTEM: the InVentry call
    # and any shares can then be granted narrowly and audited.
    $register.User = $User
    if ($Password) {
        $register.Password = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password))
    }
} else {
    $register.User = "SYSTEM"
    Write-Host "Running as SYSTEM. Note SYSTEM has no user drive mappings - keep HR_OUTPUT_DIR on a UNC path." -ForegroundColor Yellow
}

Register-ScheduledTask @register | Out-Null

Write-Host ""
Write-Host "Registered '$TaskName' - every $IntervalMinutes minute(s), $(if ($Apply) {'LIVE'} else {'dry run'})." -ForegroundColor Green
Write-Host "  Start now   : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Last result : (Get-ScheduledTaskInfo -TaskName '$TaskName').LastTaskResult   # 0 ok, 2 partial, 1 aborted"
Write-Host "  Pipeline log: <HR_SNAPSHOT_DIR>\hr_pipeline.log"
Write-Host "  Status      : <HR_SNAPSHOT_DIR>\hr_status.json  (onsite_push section)"
