<#
.SYNOPSIS
    Registers the BrightHR -> InVentry sync as a Windows Scheduled Task.

.DESCRIPTION
    Preferred deployment per the handover. Runs sync.py every N minutes under a
    service account. Defaults to dry run: pass -Apply only once the InVentry
    side is confirmed and a few days of dry-run logs look right.

.EXAMPLE
    # Dry run every 5 minutes (safe first deployment)
    .\install_scheduled_task.ps1

.EXAMPLE
    # Live, writing to InVentry, under a service account
    .\install_scheduled_task.ps1 -Apply -User "SDI\svc_brighthr" -Password (Read-Host -AsSecureString)

.NOTES
    Run from an elevated PowerShell session on SDI-DC01.
#>
[CmdletBinding()]
param(
    [string]$InstallPath = "C:\SDI\brighthr-inventry-sync",
    [string]$PythonExe   = "C:\ClaudeVision\.venv\Scripts\python.exe",
    [int]$IntervalMinutes = 5,
    [string]$TaskName = "BrightHR-InVentry Sync",
    [switch]$Apply,
    [string]$User,
    [System.Security.SecureString]$Password
)

$ErrorActionPreference = "Stop"

$syncScript = Join-Path $InstallPath "sync.py"
if (-not (Test-Path $syncScript)) { throw "sync.py not found at $syncScript" }
if (-not (Test-Path $PythonExe))  { throw "Python not found at $PythonExe" }
if (-not (Test-Path (Join-Path $InstallPath ".env"))) {
    throw "No .env at $InstallPath. Copy .env.example to .env and add the BrightHR API key first."
}

$arguments = "`"$syncScript`""
if ($Apply) {
    Write-Warning "LIVE MODE: this task will write to InVentry."
} else {
    Write-Host "Dry-run mode: the task will log intended changes only. Re-run with -Apply to go live." -ForegroundColor Yellow
}
if ($Apply) { $arguments += " --apply" }

$action = New-ScheduledTaskAction -Execute $PythonExe -Argument $arguments -WorkingDirectory $InstallPath

# Repeat indefinitely from the moment the task is registered.
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
    Write-Host "Removing existing task '$TaskName'"
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$register = @{
    TaskName    = $TaskName
    Action      = $action
    Trigger     = $trigger
    Settings    = $settings
    Description = "Syncs BrightHR Blip clock-in data to InVentry for on-site presence and fire roll call."
    RunLevel    = "Highest"
}

if ($User) {
    # A dedicated service account is preferred over SYSTEM so database access
    # can be granted narrowly and audited.
    $register.User = $User
    if ($Password) {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password))
        $register.Password = $plain
    }
} else {
    $register.User = "SYSTEM"
}

Register-ScheduledTask @register | Out-Null

Write-Host ""
Write-Host "Registered '$TaskName' - every $IntervalMinutes minute(s), $(if ($Apply) {'LIVE'} else {'dry run'})." -ForegroundColor Green
Write-Host "  Start now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Last result: (Get-ScheduledTaskInfo -TaskName '$TaskName').LastTaskResult   # 0 = OK, 2 = partial, 1 = error"
Write-Host "  Logs:       $InstallPath\logs\sync.log"
