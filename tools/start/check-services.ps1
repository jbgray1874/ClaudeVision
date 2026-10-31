<#
    Which code is each portal service on this machine running? (D-607a)

        .\tools\start\check-services.ps1

    For 8071, 8072 and 8073 it prints one of:

        down                                 nothing answered
        answering, commit X                  /api/health replied
        refused (HTTP 401), commit X         the service is up and turned the request away

    and whether X is this checkout's HEAD.

    WHY A REFUSAL IS NOT "DOWN". The one-line check given on 31 Oct printed "not answering"
    for any error, so a service that was up and wanted the key read the same as one that was
    not there. The first sends you for the key; the second sends you looking for a dead
    process. The service stamps X-SDI-Commit on every reply, the refusal included, so the
    commit can be read either way.

    WHY IT EXISTS AT ALL. HPP 03:18 was queued on a hand-started copy on 8071, running a
    commit from the day before, while the restarted service on 8072 was current. Each service
    keeps its own queue. The question "which code took the job" has to be asked of every port.

    Exits 0 when at least one service answers and every one that answers is on HEAD, 1 when
    any is on another commit or does not say, 2 when nothing answers.

    ASCII ONLY. See start-service.ps1 for why.
#>
[CmdletBinding()]
param(
    [int[]] $Ports = @(8071, 8072, 8073)
)

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$head = ""
try { $head = "$(& git -C $root rev-parse --short HEAD 2>$null)".Trim() } catch { }
if ($head) { Write-Host "  this checkout: $head" } else { Write-Host "  this checkout: HEAD unknown (git not found)" -ForegroundColor Yellow }

$up = 0
$bad = 0
foreach ($p in $Ports) {
    $state = "down"
    $commit = ""
    try {
        $reply = Invoke-WebRequest "http://localhost:$p/api/health" -UseBasicParsing -TimeoutSec 4
        $state = "answering"
        $commit = "$($reply.Headers['X-SDI-Commit'])".Trim()
    } catch {
        $refusal = $_.Exception.Response
        if ($refusal) {
            $state = "refused (HTTP $([int]$refusal.StatusCode))"
            try { $commit = "$($refusal.Headers['X-SDI-Commit'])".Trim() } catch { }
        }
    }
    if ($state -eq "down") {
        Write-Host ("  {0}  down - nothing answered" -f $p)
        continue
    }
    $up++
    $verdict = "commit not stated"
    $colour = "Yellow"
    if ($commit -and $head) {
        $n = [Math]::Min($commit.Length, $head.Length)
        if ($commit.Substring(0, $n) -eq $head.Substring(0, $n)) {
            $verdict = "matches HEAD"
            $colour = "Green"
        } else {
            $verdict = "NOT HEAD"
            $colour = "Red"
        }
    }
    if ($verdict -ne "matches HEAD") { $bad++ }
    Write-Host ("  {0}  {1}, commit {2} - {3}" -f $p, $state, $(if ($commit) { $commit } else { "?" }), $verdict) -ForegroundColor $colour
}

if ($up -eq 0) {
    Write-Host "  No service answered on any of $($Ports -join ', ')." -ForegroundColor Red
    exit 2
}
if ($bad -gt 0) {
    Write-Host "  Do not run a job until every service that answers matches HEAD." -ForegroundColor Red
    exit 1
}
Write-Host "  Every service that answers is on HEAD." -ForegroundColor Green
exit 0
