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
    [string] $TaskName = "SDI Intelligence Service",
    # THE SERVER IS SUPERVISED BY SOMETHING ELSE ENTIRELY.
    #
    # The laptop runs the service as a scheduled task. SDI-APP01 runs it as an NSSM service
    # called SDIIntelligence - configure-nssm-service.ps1 exists because of it. This script
    # knew only about the task, so on the server it would: find no task, KILL WHATEVER IS
    # LISTENING ON 8071, then print "start it yourself: install-service-task.ps1" and exit 1.
    # That is the intranet stopped, on the production box, with the remedy pointing at a
    # mechanism that machine does not use. It is the same wrong-machine fault the -Port guard
    # above was written for, one step further in.
    [string] $ServiceName = "SDIIntelligence",
    # Stop it and leave it stopped. There was no stop command for a service at all -- only
    # start and restart -- so "take the site down for five minutes" had no answer.
    [switch] $StopOnly
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

# THE PORT THE SCHEDULED TASK ITSELF STARTS ON. What is listening and what the task will
# bring back are different facts, and the restart in step 3 obeys the second. The laptop's
# task was installed for 8072 while a stray window held 8071, so "-Port 8071" -- the remedy
# the refusal below offered -- ended the window, started the task on 8072, and reported
# 8071 as down. 0 when there is no task (the server's NSSM service) or it names no port.
$taskPort = 0
$taskHere = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($taskHere) {
    foreach ($action in @($taskHere.Actions)) {
        if ("$($action.Arguments)" -match '-Port\s+(\d+)') { $taskPort = [int]$Matches[1] }
    }
}
$whatIsOn = 'Get-NetTCPConnection -LocalPort {0} -State Listen | ForEach-Object {{ Get-CimInstance Win32_Process -Filter "ProcessId=$($_.OwningProcess)" }} | Select-Object ProcessId, CreationDate, CommandLine'

if ($serving.Count -gt 0 -and ($serving -notcontains $Port) -and ($taskPort -ne $Port)) {
    $me = [System.Net.Dns]::GetHostName()
    Write-Host ""
    Write-Host ("  STOP. {0} is not serving {1} - nothing is listening on it here." -f $me, $Port) -ForegroundColor Red
    Write-Host ("  This machine is listening on {0}." -f ($serving -join ", ")) -ForegroundColor Red
    if ($taskPort -gt 0) {
        Write-Host ("  Its scheduled task starts the service on {0}." -f $taskPort) -ForegroundColor Red
    }
    Write-Host "  The estimating laptop serves 8072; SDI-APP01 serves 8071. Both have a" -ForegroundColor Red
    Write-Host "  C:\ClaudeVision, so the prompt looks the same on either." -ForegroundColor Red
    Write-Host ""
    $offer = $serving[0]
    if ($taskPort -gt 0) { $offer = $taskPort }
    Write-Host ("  Either re-run here with -Port {0}, or run this ON the other machine." -f $offer) -ForegroundColor Yellow
    Write-Host "  Nothing has been stopped." -ForegroundColor Green
    Write-Host ""
    exit 2
}

# LISTENING ON THE PORT ASKED FOR, BUT NOT BY THE TASK. Restarting would end that listener
# and bring the task back on its own port, then report this one as down -- a success read
# as a failure, which is the fault this whole step exists to prevent.
if ($taskPort -gt 0 -and $taskPort -ne $Port -and ($serving -contains $Port)) {
    $me = [System.Net.Dns]::GetHostName()
    Write-Host ""
    Write-Host ("  STOP. Something on {0} is listening on {1}, but this machine's scheduled" -f $me, $Port) -ForegroundColor Red
    Write-Host ("  task starts the service on {0}. Restarting would end the {1} listener, bring" -f $taskPort, $Port) -ForegroundColor Red
    Write-Host ("  the service back on {0}, and then report {1} as down." -f $taskPort, $Port) -ForegroundColor Red
    Write-Host ""
    Write-Host ("  Restart the task's own service:      -Port {0}" -f $taskPort) -ForegroundColor Yellow
    Write-Host ("  Or make {0} this machine's port:   .\tools\start\install-service-task.ps1 -Port {0}" -f $Port) -ForegroundColor Yellow
    Write-Host ("  What is on {0}:" -f $Port) -ForegroundColor Yellow
    Write-Host ("    " + ($whatIsOn -f $Port)) -ForegroundColor Yellow
    Write-Host "  Nothing has been stopped." -ForegroundColor Green
    Write-Host ""
    exit 2
}

# ASKED FOR THE TASK'S PORT WHILE SOMETHING ELSE HOLDS ANOTHER. The restart goes ahead --
# the task is what serves this port -- but the other listener is not this task, is left
# alone, and is very likely still serving old code.
if ($taskPort -eq $Port -and $serving.Count -gt 0 -and ($serving -notcontains $Port)) {
    foreach ($other in $serving) {
        Write-Host ("  note: {0} is also listening here and is not the scheduled task; it is left alone." -f $other) -ForegroundColor Yellow
        Write-Host ("    find it:  " + ($whatIsOn -f $other)) -ForegroundColor Yellow
    }
}

# -- 1. STOP WHATEVER SUPERVISES IT HERE ----------------------------------------------
#
# Two machines, two supervisors, and this script only knew one of them. Asked before
# anything is stopped, so the restart at step 3 uses the same answer the stop did.
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$svc  = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

if ($task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "  stopped the scheduled task '$TaskName'"
    } else {
        Write-Host "  the scheduled task '$TaskName' was not running"
    }
} elseif ($svc) {
    # NSSM RESTARTS WHAT YOU KILL, which is the whole point of it and is exactly why the
    # port must not be killed while the supervisor is still running: NSSM would bring the
    # OLD code straight back, the health check would pass, and the restart would report
    # success having changed nothing. The service is stopped first and properly.
    Write-Host "  supervised by the Windows service '$ServiceName' (state: $($svc.Status))"
    if ($svc.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
        $svc.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(20))
        Write-Host "  stopped the service"
    }
} else {
    Write-Host "  NOTHING SUPERVISES THIS SERVICE HERE." -ForegroundColor Yellow
    Write-Host "  No scheduled task '$TaskName' and no service '$ServiceName'." -ForegroundColor Yellow
    Write-Host "  It is a hand-started window, so this script can stop it but cannot start" -ForegroundColor Yellow
    Write-Host "  it again. Restart it with:  .\tools\start\start-service.ps1 -Port $Port" -ForegroundColor Yellow
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
if ($StopOnly) {
    Write-Host ""
    Write-Host "  stopped. Nothing restarted (-StopOnly)." -ForegroundColor Green
    Write-Host "  Start it again with this script without -StopOnly." -ForegroundColor Green
    exit 0
}

if ($task) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "  started the scheduled task"
} elseif ($svc) {
    Start-Service -Name $ServiceName -ErrorAction SilentlyContinue
    Write-Host "  started the service '$ServiceName'"
} else {
    Write-Host "  Nothing here can start it again - it was a hand-started window." -ForegroundColor Yellow
    Write-Host "      .\tools\start\start-service.ps1 -Port $Port" -ForegroundColor Yellow
    exit 1
}

# uvicorn has to import the app before it listens; reporting failure while it is still
# starting would be its own false alarm. POLLED, NOT A FIXED WAIT: eight seconds was the
# whole allowance, and a slow start read as a dead service. Up to 60 seconds, every 2.

# -- 4. IS IT SERVING THE CODE ON DISK? -------------------------------------------------
#
# The only question worth asking. git is on the PATH in THIS shell and not in the
# virtualenv the service starts from, so the comparison can be made here and nowhere else.
$head = Get-HeadCommit $Root

$health = $null
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod "http://localhost:$Port/api/health" -TimeoutSec 4
        break
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -eq 401) { break }
    }
}

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
    # -- ANOTHER SERVICE ON THIS MACHINE, ON OTHER CODE (D-607) -------------------------
    #
    # HPP 03:18 was claimed by a runner reporting to 8071 while this script had restarted
    # 8072. Each service keeps its own queue, so a page opened on 8071, or a runner polling
    # it, kept the old code, and this script said nothing because 8071 was not its port.
    foreach ($other in @(8071, 8072, 8073)) {
        if ($other -eq $Port) { continue }
        if (@(Get-NetTCPConnection -LocalPort $other -State Listen -ErrorAction SilentlyContinue).Count -eq 0) { continue }
        # A REFUSAL IS AN ANSWER (D-607a). A 401 is a service turning away a request without
        # the key, not a service that is down, and the commit header rides on the refusal too.
        $otherCommit = ""
        $otherState = "did not answer"
        try {
            $reply = Invoke-WebRequest "http://localhost:$other/api/health" -UseBasicParsing -TimeoutSec 4
            $otherState = "answered"
            $otherCommit = "$($reply.Headers['X-SDI-Commit'])".Trim()
        } catch {
            $refusal = $_.Exception.Response
            if ($refusal) {
                $otherState = "refused the request (HTTP $([int]$refusal.StatusCode))"
                try { $otherCommit = "$($refusal.Headers['X-SDI-Commit'])".Trim() } catch { }
            }
        }
        if (-not $otherCommit -or $otherCommit -eq "unknown") {
            Write-Host ("  note: {0} is also listening here; it {1} and did not say which commit it runs." -f $other, $otherState) -ForegroundColor Yellow
            Write-Host ("    find it:  " + ($whatIsOn -f $other)) -ForegroundColor Yellow
        } elseif ($head -and $otherCommit -ne $head) {
            Write-Host ""
            Write-Host ("  ALSO SERVING: {0} is on {1}, not this checkout's {2}." -f $other, $otherCommit, $head) -ForegroundColor Red
            Write-Host ("  A page opened on {0}, or a runner reporting to it, still gets that code." -f $other) -ForegroundColor Red
            Write-Host "  End it and start it again from this checkout, or stop it and use this port." -ForegroundColor Yellow
            Write-Host ("    find it:  " + ($whatIsOn -f $other)) -ForegroundColor Yellow
        }
    }
} catch {
    if ($_.Exception.Response -and $_.Exception.Response.StatusCode.value__ -eq 401) {
        Write-Host "  answering on $Port (401 - key required, which is fine)" -ForegroundColor Green
    } else {
        Write-Host ""
        Write-Host "  NOT answering on $Port after 60 seconds." -ForegroundColor Red

        # -- 5. NOT ANSWERING: THE REASON, HERE ----------------------------------------
        #
        # The old message pointed at a dated log file and never printed its name, twice, while
        # the service was up on another port. What is known is gathered and shown instead.

        # FIRST: IS THE SERVICE UP ON ANOTHER PORT? Then the portal works now, on that port.
        foreach ($other in @(8071, 8072, 8073)) {
            if ($other -eq $Port) { continue }
            try {
                $h2 = Invoke-RestMethod "http://localhost:$other/api/health" -TimeoutSec 4
                $c2 = "$($h2.commit)".Trim()
                $tag = ""
                if ($head -and $c2 -eq $head) { $tag = " - the code on disk" }
                Write-Host ("  The service IS answering on {0}, serving {1}{2}." -f $other, $c2, $tag) -ForegroundColor Green
                Write-Host ("  Use http://localhost:{0}/estimating now." -f $other) -ForegroundColor Green
                # WHO RUNS IT, NAMED: the listener, the starter that launched it, and whatever
                # launched that: a scheduled task, an NSSM service, or a window somebody opened.
                foreach ($conn in @(Get-NetTCPConnection -LocalPort $other -State Listen -ErrorAction SilentlyContinue)) {
                    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)" -ErrorAction SilentlyContinue
                    $hop = 0
                    while ($proc -and $hop -lt 3) {
                        Write-Host ("    pid {0} started {1}: {2}" -f $proc.ProcessId, $proc.CreationDate, $proc.CommandLine) -ForegroundColor Yellow
                        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)" -ErrorAction SilentlyContinue
                        $hop++
                    }
                }
                Write-Host ("  To restart that one instead:  .\tools\start\restart-service.ps1 -Port {0}" -f $other) -ForegroundColor Yellow
            } catch { }
        }

        # SECOND: THE SCHEDULED TASK'S OWN LAST RESULT.
        if ($task) {
            $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction SilentlyContinue
            if ($info) {
                Write-Host ("  scheduled task: last run {0}, result 0x{1:X}" -f $info.LastRunTime, $info.LastTaskResult) -ForegroundColor Yellow
            }
        }

        # THIRD: THE LOG, NAMED AND QUOTED. Opened for read while a running starter may hold it;
        # it mixes UTF-8 stamps with UTF-16 console output, so the NULs are dropped to read it.
        $logDir = Join-Path $Root "output\logs"
        $day = Get-Date -Format "yyyy-MM-dd"
        $logs = @((Join-Path $logDir ("service-{0}-{1}.log" -f $Port, $day)),
                  (Join-Path $logDir ("service-{0}.log" -f $day))) | Where-Object { Test-Path -LiteralPath $_ }
        if (@($logs).Count -gt 0) {
            $log = @($logs)[0]
            Write-Host "  last lines of $log :" -ForegroundColor Yellow
            try {
                $fs = [System.IO.File]::Open($log, 'Open', 'Read', 'ReadWrite')
                $sr = New-Object System.IO.StreamReader($fs)
                $text = $sr.ReadToEnd()
                $sr.Close()
                ($text -replace "`0", "") -split "`r?`n" | Where-Object { $_.Trim() } |
                    Select-Object -Last 25 | ForEach-Object { Write-Host "    $_" }
            } catch {
                Write-Host "    (could not read it: $($_.Exception.Message))" -ForegroundColor Yellow
            }
        } else {
            Write-Host "  no service log for today under $logDir" -ForegroundColor Yellow
        }
        exit 1
    }
}
