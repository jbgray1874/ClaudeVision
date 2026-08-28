<#
    Restart the SDI Intelligence service so it serves the code on disk.

        .\tools\start\restart-service.ps1
        .\tools\start\restart-service.ps1 -Port 8073

    WHY THIS EXISTS, WHICH IS NOT OBVIOUS UNTIL IT HAS COST YOU AN AFTERNOON.

    "Stop-ScheduledTask; Start-ScheduledTask" looks like a restart and can
    restart nothing at all. Both commands return cleanly, the site keeps
    answering, and it keeps answering with the code it imported hours ago.

    Two things combine to produce that:

      1. Stopping the task does not reliably kill the python process serving
         the site. The task's action is powershell.exe, which then runs python
         as a child; when the wrapper goes, the child can be left holding the
         port with nothing supervising it.

      2. start-service.ps1 REFUSES a port that is already held - deliberately,
         so the five-minute sweep cannot trample a running site. So the newly
         started task finds the port taken, exits, and the orphan carries on
         serving.

    The symptom reaches an estimator as a page failing on a field the service
    has never heard of. That reads as a broken feature, not as a stale process,
    and there is nothing on the page that could tell them otherwise.

    So this stops the task, ENDS WHATEVER IS ACTUALLY LISTENING, starts the
    task again, and then checks the commit the SITE reports against this
    checkout's HEAD - because "it restarted" and "it is running the new code"
    are different claims and only the second one matters.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [int]    $Port = 8072,
    [string] $Root = "",
    [string] $TaskName = "SDI Intelligence Service"
)

$ErrorActionPreference = "Stop"

if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) {
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if (-not $here) { throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision" }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}


# -- WHAT COMMIT IS THIS CHECKOUT AT, ON A MACHINE THAT MAY NOT HAVE GIT --------------
#
# `& git ...` was called directly here, and SDI-APP01 has no git. With
# $ErrorActionPreference = "Stop" that is a CommandNotFoundException BEFORE the command
# runs, so the `2>$null` never gets a chance -- a red CommandNotFoundException in the
# middle of a restart that had, in fact, worked:
#
#     restart-service.ps1 : The term 'git' is not recognized ...
#
# and then the service answered ok on the next line. An error printed by a step that did
# not fail is how a working deploy gets rolled back.
#
# THE FALLBACK IS THE INTERESTING HALF. Without git that machine could never name its own
# build, so /api/health reported "commit": "unknown" and no one could tell a current server
# from a stale one -- which is the exact question this whole restart exists to answer.
# push-to-server.ps1 runs on the laptop, WHICH HAS GIT, and leaves the sha in .sdi-commit
# beside the code it copied. So the answer travels with the deploy instead of being
# recomputed somewhere it cannot be.
function Get-HeadCommit([string]$RepoRoot) {
    $exe = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        foreach ($cand in @("C:\Program Files\Git\cmd\git.exe",
                            "C:\Program Files (x86)\Git\cmd\git.exe")) {
            if (Test-Path -LiteralPath $cand) { $exe = $cand; break }
        }
    }
    if ($exe) {
        # A PRESENT git CAN STILL THROW. safe.directory refuses a repository cloned by
        # somebody else, and under $ErrorActionPreference = "Stop" that stops the script --
        # so the service does not start because a VERSION STRING could not be resolved.
        # Never worth it: the stamp is diagnostic, the service is the point.
        $prevEA = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $sha = (& $exe -C $RepoRoot rev-parse --short HEAD 2>$null)
            if ($LASTEXITCODE -eq 0 -and $sha) { return "$sha".Trim() }
        } catch { }
        finally { $ErrorActionPreference = $prevEA }
    }
    $stamp = Join-Path $RepoRoot ".sdi-commit"
    if (Test-Path -LiteralPath $stamp) {
        $written = (Get-Content -LiteralPath $stamp -TotalCount 1)
        if ($written) { return "$written".Trim() }
    }
    return ""
}

Write-Host "Restarting the SDI Intelligence service on port $Port" -ForegroundColor Cyan

# -- 0. IS THIS THE MACHINE THAT SERVES THAT PORT? ------------------------------------
#
# THE FAILURE THIS PREVENTS, WHICH ALREADY HAPPENED. `-Port 8071` was run on the LAPTOP,
# which serves 8072. The port only drove the kill and the health check; the scheduled task
# is machine-wide and was restarted regardless. So it stopped the running service, started
# it again, then looked at a port nothing on that machine has ever served and reported
#
#     NOT answering on 8071.
#
# A restart that succeeded, reported as a failure, on the wrong computer -- and the reader's
# reasonable conclusion is that the SERVER is broken, which sends them to a log on a machine
# where nothing is wrong. Both boxes have a C:\ClaudeVision, so the prompt is identical and
# there is nothing on screen to tell them apart.
#
# Checked BEFORE anything is stopped. Refusing after the kill would leave the same mess.
$serving = @()
foreach ($candidate in @(8071, 8072, 8073)) {
    $listening = @(Get-NetTCPConnection -LocalPort $candidate -State Listen -ErrorAction SilentlyContinue)
    if ($listening.Count -gt 0) { $serving += $candidate }
}
if ($serving.Count -gt 0 -and ($serving -notcontains $Port)) {
    $me = [System.Net.Dns]::GetHostName()
    Write-Host ""
    Write-Host ("  STOP. {0} is not serving {1} - nothing is listening on it here." -f $me, $Port) -ForegroundColor Red
    Write-Host ("  This machine is listening on {0}." -f ($serving -join ", ")) -ForegroundColor Red
    Write-Host "  The estimating laptop serves 8072; SDI-APP01 serves 8071. Both have a" -ForegroundColor Red
    Write-Host "  C:\ClaudeVision, so the prompt looks the same on either." -ForegroundColor Red
    Write-Host ""
    Write-Host ("  Either re-run here with -Port {0}, or run this ON the other machine." -f $serving[0]) -ForegroundColor Yellow
    Write-Host "  Nothing has been stopped." -ForegroundColor Green
    Write-Host ""
    exit 2
}

# -- 1. STOP THE TASK, IF THERE IS ONE ------------------------------------------------
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "  stopped the scheduled task"
    } else {
        Write-Host "  the scheduled task was not running"
    }
} else {
    Write-Host "  no scheduled task installed - install-service-task.ps1 sets one up" -ForegroundColor Yellow
}

# -- 2. END WHATEVER IS ACTUALLY LISTENING --------------------------------------------
#
# THE STEP THE OBVIOUS RESTART MISSES. Named before it is killed: a pid and a start time
# is what tells you afterwards whether you ended the thing you meant to.
Start-Sleep -Seconds 1
$held = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($held.Count -eq 0) {
    Write-Host "  nothing was left listening on $Port"
} else {
    foreach ($procId in @($held | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
        if ($p) {
            $started = "unknown"
            if ($p.StartTime) { $started = $p.StartTime.ToString("HH:mm:ss") }
            Write-Host "  ending pid $procId ($($p.ProcessName), started $started)" -ForegroundColor Yellow
        }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 800
}

# -- 3. START IT AGAIN ------------------------------------------------------------------
if ($task) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "  started the scheduled task"
} else {
    Write-Host "  start it yourself:  .\tools\start\install-service-task.ps1" -ForegroundColor Yellow
    exit 1
}

# uvicorn has to import the app before it listens; reporting failure while it is still
# starting would be its own false alarm.
Start-Sleep -Seconds 8

# -- 4. IS IT SERVING THE CODE ON DISK? -------------------------------------------------
#
# The only question worth asking. git is on the PATH in THIS shell and not in the
# virtualenv the service starts from, so the comparison can be made here and nowhere else.
$head = Get-HeadCommit $Root

try {
    $health = Invoke-RestMethod "http://localhost:$Port/api/health" -TimeoutSec 6
    $serving = "$($health.commit)".Trim()
    if ($head -and $serving -and $serving -ne "unknown" -and $serving -ne $head) {
        Write-Host ""
        Write-Host "  STILL STALE: serving $serving, this checkout is at $head." -ForegroundColor Red
        Write-Host "  Something took the port again. Find it and run this script once more:" -ForegroundColor Yellow
        Write-Host "    Get-NetTCPConnection -LocalPort $Port -State Listen |" -ForegroundColor Yellow
        Write-Host "      ForEach-Object { Get-Process -Id `$_.OwningProcess }" -ForegroundColor Yellow
        exit 1
    }
    Write-Host ""
    Write-Host "  serving commit $serving$(if ($head -and $serving -eq $head) { ' - matches this checkout' })" -ForegroundColor Green
    Write-Host "  http://localhost:$Port/estimating" -ForegroundColor Green
} catch {
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -eq 401) {
        Write-Host "  answering on $Port (401 - key required, which is fine)" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "  NOT answering on $Port." -ForegroundColor Red
        Write-Host "  The reason is in $Root\output\logs\service-<date>.log" -ForegroundColor Yellow
        exit 1
    }
}
