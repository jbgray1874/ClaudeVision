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
# THE WATCHER IS ENDED, ITS LOCK CLEARED, AND IT IS HEARD AGAIN BEFORE THIS SAYS DONE. On
# 13 Nov 2026 this step stopped and started the task and printed nothing. A stopped watcher
# cannot release its lock, the new one refuses a lock touched in the last ten minutes, and
# the page said "no self-running watcher is connected" with every runner on the new build.
Step "restart the Self-Running watcher" {
    $taskName = "SDI AI Estimate Self-Running"
    if (-not (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue)) {
        Write-Host "  no '$taskName' task on this machine: nothing to restart" -ForegroundColor Yellow
        return
    }
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    $watchers = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*self_running.py*" })
    foreach ($w in $watchers) { Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue }
    if ($watchers.Count) { Write-Host "  ended the watcher (pid $(($watchers | ForEach-Object { $_.ProcessId }) -join ', '))" }
    Start-Sleep -Seconds 2
    $ledger = Join-Path $root "output\live_enquiry\ledger.json"
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        $ledgerEnv = Select-String -Path $envFile -Pattern '^\s*SDI_LIVE_ENQUIRY_LEDGER\s*=\s*(.+?)\s*$' |
            Select-Object -First 1
        if ($ledgerEnv) { $ledger = $ledgerEnv.Matches[0].Groups[1].Value.Trim('"') }
    }
    $lock = Join-Path (Split-Path -Parent $ledger) "live_enquiry.lock"
    if (Test-Path $lock) {
        $holder = ((Get-Content -LiteralPath $lock -ErrorAction SilentlyContinue) -split "\s+")[0]
        if (-not ($holder -as [int]) -or -not (Get-Process -Id ([int]$holder) -ErrorAction SilentlyContinue)) {
            Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
            Write-Host "  cleared the lock left by the watcher that was ended"
        } else {
            Write-Host "  the lock is held by pid $holder, which is still running: the watcher will refuse to start" -ForegroundColor Red
            $global:LASTEXITCODE = 10
            return
        }
    }
    Start-ScheduledTask -TaskName $taskName
    $heard = $false
    $answered = $false
    foreach ($try in 1..9) {
        Start-Sleep -Seconds 5
        try { $sr = Invoke-RestMethod -Uri "http://localhost:8071/api/estimate/self-running" -TimeoutSec 5 } catch { continue }
        $answered = $true
        if ($sr.watcher.connected -and $sr.watcher.seconds_since -le 20) { $heard = $true; break }
    }
    if ($heard) { Write-Host "  the watcher is connected (heard $($sr.watcher.seconds_since)s ago)" -ForegroundColor Green }
    elseif (-not $answered) {
        # NOT ASKED IS NOT "NOT RUNNING": a false alarm sends someone to mend a working watcher.
        Write-Host "  started the task. 8071 did not answer the question, so the watcher is NOT CONFIRMED: read the estimating page" -ForegroundColor Yellow
    }
    else {
        Write-Host "  THE WATCHER WAS NOT HEARD in 45 seconds. Read output\live_enquiry\self_running.log" -ForegroundColor Red
        $global:LASTEXITCODE = 10
    }
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
