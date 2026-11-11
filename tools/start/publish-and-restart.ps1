<#
.SYNOPSIS
    Publish the checkout and restart everything, stopping at the first step that refuses.

        .\tools\start\publish-and-restart.ps1 -Commit 0231b899

    The pasted block (SDI_Intelligence_HANDOFF_STATE_2.md, section 0) carried on after a step
    refused: on 11 Nov 2026 the main runner refused its restart because jobs were running, and
    the block went on to update slot 2 under a running job. This is that block as one script.

    ORDER, AND WHY. Nothing is touched until the runners are known to be idle: the two runner
    scripts refuse while a job is running, so they are asked FIRST with -CheckOnly semantics
    (a busy runner stops the whole publish before any service restarts). Then: push the portal
    branch, bring main-2026 forward (fast-forward only), restart both services, the main runner,
    slot 2 and the Self-Running watcher, and read every service and runner back.
#>
param(
    [Parameter(Mandatory = $true)] [string] $Commit,
    [int] $Slot = 2,
    [switch] $NoSlot
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $root

function Step([string] $what, [scriptblock] $do) {
    Write-Host ""
    Write-Host "== $what" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $do
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "STOPPED at: $what (exit $LASTEXITCODE). Nothing after it was run." -ForegroundColor Red
        Write-Host "Send the output above." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Step "the fix $Commit is in this checkout" { git merge-base --is-ancestor $Commit HEAD }

# EVERY RUNNER IDLE BEFORE ANYTHING RESTARTS: a service restart is harmless to a running job,
# but a half-updated grid (services new, runners old) is what 11 Nov left behind.
Step "no runner on this machine is in the middle of a job" {
    $busy = @()
    foreach ($svc in @("http://localhost:8071", "http://localhost:8072")) {
        try { $seen = Invoke-RestMethod -Uri "$svc/api/estimate/runners" -TimeoutSec 5 } catch { continue }
        foreach ($r in @($seen.runners)) {
            if ($r.running) { $busy += "$($r.runner_id): $($r.running.drawing_number) for $($r.running.client), $($r.running.seconds)s in (service $svc)" }
        }
    }
    if ($busy.Count -gt 0) {
        Write-Host "  Jobs are running:" -ForegroundColor Yellow
        $busy | Select-Object -Unique | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        Write-Host "  Wait until Grid Control shows them filed, then run this again." -ForegroundColor Red
        $global:LASTEXITCODE = 6
    }
}

Step "push the portal branch" { git push origin HEAD }
Step "fetch the laptop repository's main-2026" { git fetch origin main-2026 }
Step "main-2026 moves forward only" { git merge-base --is-ancestor FETCH_HEAD HEAD }
Step "push main-2026" { git push origin HEAD:main-2026 }
Step "restart the service on 8072" { & "$root\tools\start\restart-service.ps1" }
Step "restart the service on 8071" { & "$root\tools\start\restart-service.ps1" -Port 8071 -TaskName "SDI Intelligence Service 8071" }
Step "restart the main runner" { & "$root\tools\start\restart-runner.ps1" }
if (-not $NoSlot) {
    Step "update runner slot $Slot" { & "$root\tools\start\install-runner-slot.ps1" -Slot $Slot }
}
Step "restart the Self-Running watcher" {
    Stop-ScheduledTask -TaskName "SDI AI Estimate Self-Running" -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName "SDI AI Estimate Self-Running"
}
Step "every service on this checkout" { & "$root\tools\start\check-services.ps1" -Ports 8071,8072 }

# THE RUNNERS' OWN BUILDS, FRESHLY HEARD, not only the services'.
$head = "$(git rev-parse --short=7 HEAD)".Trim()
Write-Host ""
Write-Host "== runners, as the services hear them (waiting 20 s for fresh check-ins)" -ForegroundColor Cyan
Start-Sleep -Seconds 20
$bad = 0
foreach ($svc in @("http://localhost:8071", "http://localhost:8072")) {
    try { $seen = Invoke-RestMethod -Uri "$svc/api/estimate/runners" -TimeoutSec 5 } catch { Write-Host "  $svc did not answer" -ForegroundColor Red; $bad++; continue }
    foreach ($r in @($seen.runners)) {
        $b = "$($r.build)"
        $ok = $r.online -and $b.StartsWith($head)
        if (-not $ok) { $bad++ }
        Write-Host ("  {0}  {1}  build {2}  seen {3}s ago  {4}" -f $svc, $r.runner_id, $b.Substring(0, [Math]::Min(7, $b.Length)), $r.seconds_since_seen, $(if ($ok) { "OK" } else { "NOT on $head or not online" })) -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
    }
}
if ($bad -gt 0) { Write-Host "Not every runner is on $head and online: send this output." -ForegroundColor Red; exit 9 }
Write-Host "Every service and every runner is on $head." -ForegroundColor Green
