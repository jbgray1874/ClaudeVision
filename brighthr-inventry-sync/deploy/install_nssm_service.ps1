<#
.SYNOPSIS
    Installs the sync as a Windows service via NSSM (alternative to Task Scheduler).

.DESCRIPTION
    Runs sync.py with --loop as a persistent service. Use this instead of the
    scheduled task if a resident process is preferred; do not run both, or two
    syncs will write to InVentry at once.

.EXAMPLE
    .\install_nssm_service.ps1 -Apply

.NOTES
    Requires nssm.exe on PATH (https://nssm.cc). Run elevated.
#>
[CmdletBinding()]
param(
    [string]$InstallPath = "C:\SDI\brighthr-inventry-sync",
    [string]$PythonExe   = "C:\ClaudeVision\.venv\Scripts\python.exe",
    [string]$ServiceName = "BrightHRInVentrySync",
    [switch]$Apply,
    [string]$User
)

$ErrorActionPreference = "Stop"

$nssm = (Get-Command nssm.exe -ErrorAction SilentlyContinue).Source
if (-not $nssm) { throw "nssm.exe not found on PATH. Download it from https://nssm.cc" }

$syncScript = Join-Path $InstallPath "sync.py"
if (-not (Test-Path $syncScript)) { throw "sync.py not found at $syncScript" }
if (-not (Test-Path (Join-Path $InstallPath ".env"))) {
    throw "No .env at $InstallPath. Copy .env.example to .env and add the BrightHR API key first."
}

if (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) {
    Write-Host "Removing existing service '$ServiceName'"
    & $nssm stop $ServiceName confirm | Out-Null
    & $nssm remove $ServiceName confirm | Out-Null
    Start-Sleep -Seconds 2
}

$arguments = "`"$syncScript`" --loop"
if ($Apply) {
    Write-Warning "LIVE MODE: this service will write to InVentry."
    $arguments += " --apply"
} else {
    Write-Host "Dry-run mode: the service will log intended changes only." -ForegroundColor Yellow
}

& $nssm install $ServiceName $PythonExe $arguments | Out-Null
& $nssm set $ServiceName AppDirectory $InstallPath | Out-Null
& $nssm set $ServiceName DisplayName "BrightHR to InVentry Sync" | Out-Null
& $nssm set $ServiceName Description "Syncs BrightHR Blip clock-in data to InVentry for on-site presence and fire roll call." | Out-Null
& $nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null

# Capture stdout/stderr; the script also writes its own rolling log.
$logDir = Join-Path $InstallPath "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
& $nssm set $ServiceName AppStdout (Join-Path $logDir "service_stdout.log") | Out-Null
& $nssm set $ServiceName AppStderr (Join-Path $logDir "service_stderr.log") | Out-Null
& $nssm set $ServiceName AppRotateFiles 1 | Out-Null
& $nssm set $ServiceName AppRotateBytes 10485760 | Out-Null

# Restart on failure, backing off so a BrightHR outage does not hot-loop.
& $nssm set $ServiceName AppExit Default Restart | Out-Null
& $nssm set $ServiceName AppRestartDelay 30000 | Out-Null

if ($User) { & $nssm set $ServiceName ObjectName $User | Out-Null }

& $nssm start $ServiceName | Out-Null

Write-Host ""
Write-Host "Service '$ServiceName' installed and started ($(if ($Apply) {'LIVE'} else {'dry run'}))." -ForegroundColor Green
Write-Host "  Status: Get-Service $ServiceName"
Write-Host "  Stop:   nssm stop $ServiceName"
Write-Host "  Logs:   $logDir\sync.log"
