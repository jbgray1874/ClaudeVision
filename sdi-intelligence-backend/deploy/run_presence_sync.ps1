<#
.SYNOPSIS
    One presence cycle: ask BrightHR who is clocked in, push it to InVentry.

.DESCRIPTION
    What the scheduled task runs. Two steps:

      1. hr_blip.py         - query BrightHR Blip, write the on-site snapshot
      2. hr_onsite_push.py  - reconcile InVentry's register against it

    Defaults to a DRY RUN. Pass -Apply to write to InVentry.

    Exit codes are meaningful, because Task Scheduler records them:
      0  clean
      2  ran, but something was suppressed or partially failed
      1  aborted without writing - a guard tripped, or a system was unreachable

    If the Blip query is degraded or the snapshot is stale, the push refuses
    rather than publishing an under-reported on-site list. That is deliberate:
    an incomplete evacuation list is worse than one that has not moved.

.EXAMPLE
    .\run_presence_sync.ps1
    .\run_presence_sync.ps1 -Apply
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Python = "C:\ClaudeVision\.venv\Scripts\python.exe",
    [string]$BackendDir = "$PSScriptRoot\.."
)

$ErrorActionPreference = "Continue"
Set-Location $BackendDir

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "$stamp  presence sync starting$(if (-not $Apply) { ' (dry run)' })"

& $Python hr_blip.py
$blip = $LASTEXITCODE
if ($blip -eq 1) {
    Write-Host "Blip query failed outright - not pushing anything to InVentry."
    exit 1
}
if ($blip -eq 2) {
    # Degraded: some per-employee queries failed. The push applies its own
    # guard against this, so let it decide rather than second-guessing here.
    Write-Host "Blip query degraded - the push will decide whether to publish."
}

$pushArgs = @("hr_onsite_push.py")
if ($Apply) { $pushArgs += "--apply" }
& $Python @pushArgs
$push = $LASTEXITCODE

Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  blip=$blip push=$push"
exit $push
