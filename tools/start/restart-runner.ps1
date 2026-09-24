<#
    Restart the SDI estimating runner so it runs the code on disk.

        .\tools\start\restart-runner.ps1
        .\tools\start\restart-runner.ps1 -Pull
        .\tools\start\restart-runner.ps1 -Pull -Clean

    WHY THIS EXISTS. There was no such command. restart-service.ps1 has existed
    for the SERVICE since the day a restart failed to restart anything, and the
    runner - the process that actually costs jobs - had nothing. Stopping it was
    a five-line incantation printed inside a Write-Host in start-runner.ps1, to be
    copied out of a terminal by hand.

    THE COST OF NOT HAVING IT, ON 18 SEPTEMBER 2026. 401912-02 was run three
    times in twenty minutes. Every run stamped

        [build] engine source: 2314342 +local edits

    while the branch it was meant to be on had moved four commits ahead - one of
    them the fix for the very crash that ended each run. Three runs, three
    identical tracebacks, nothing filed, and an afternoon gone. A pull had been
    asked for each time and the runner was never restarted, so the pull could not
    reach the process.

    WHICH MACHINE THIS IS FOR. The runner, not the service. The runner is the box
    with a SOLIDWORKS seat, Excel, and somebody logged in - it holds the checkout
    the ENGINE runs from and it is the only thing a `git pull` on that machine
    affects. The service on 8071 or 8072 QUEUES jobs; restarting it does nothing
    whatever to the code that costs them. That distinction is the one people get
    wrong, so this script says which machine it is on before it does anything.

    STOPPING A SCHEDULED TASK IS NOT ENOUGH, which is the same thing
    restart-service.ps1 exists to say: the task's action is powershell.exe, which
    starts python as a CHILD, and when the wrapper goes the child can be left
    running. So the task is stopped AND every runner process is ended by name.

    ONE RUNNER IS TWO PROCESSES. A virtualenv python.exe on Windows is a launcher
    that starts the base interpreter as a child, so a single healthy runner shows
    up twice with identical command lines. Both are ended; neither is counted as
    a second runner.

    ASCII ONLY. See start-service.ps1 for why.
#>
[CmdletBinding()]
param(
    [string] $Root     = "",
    [string] $TaskName = "SDI Estimating Runner",
    # Pull first. Off by default because this script's job is to restart, and a
    # pull that fails - a dirty tree, a conflict - must not read as a failed
    # restart. With -Pull it is done FIRST and a failure stops everything, so a
    # runner is never restarted onto a half-updated checkout.
    [switch] $Pull,
    # Delete __pycache__ before starting.
    #
    # WHY IT IS HERE AND WHY IT IS OFF. Python decides a .pyc is stale from the
    # source's mtime and size, and a copied, restored or share-hosted tree can
    # defeat both. The tell is a traceback whose source lines are NONSENSE - a
    # comment or a dict literal printed where a function call must be, because
    # the line numbers come from the compiled code and the text is read fresh
    # off disk. That was on screen for 401912-02. It is rare, deleting the
    # caches costs one slow import, and it is not done silently because a
    # command that quietly deletes things is a command people stop trusting.
    [switch] $Clean,
    # Do not start it again - just stop it.
    [switch] $StopOnly,
    # The service this runner reports to, asked at the end whether it sees exactly one
    # runner on the commit on disk. Empty means SDI_SERVICE_URL, else this machine's
    # SDI_PORT, else 8071. On a runner server that reports to a portal on another box,
    # pass that box: -Service http://<portal-server>:8071
    [string] $Service = "",
    [string] $ApiKey  = $env:SDI_API_KEY
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

$me = [System.Net.Dns]::GetHostName()
Write-Host "Restarting the SDI estimating runner on $me" -ForegroundColor Cyan
Write-Host "  checkout: $Root"

# -- 0. IS THERE A RUNNER ON THIS MACHINE AT ALL? -------------------------------------
#
# THE WRONG-MACHINE FAULT, WHICH restart-service.ps1 ALREADY PAID FOR. Every box has a
# C:\ClaudeVision and an identical prompt. Running this on the service box would stop
# nothing, start nothing, and report success - and the reader would conclude the runner
# had been restarted when the machine that actually runs jobs was untouched.
$runnerScript = Join-Path $Root "tools\runner\sdi_estimate_runner.py"
$python       = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $runnerScript)) {
    Write-Host ""
    Write-Host "  STOP. There is no runner in this checkout ($runnerScript)." -ForegroundColor Red
    Write-Host "  This is not the runner machine. The runner is the box with a SOLIDWORKS" -ForegroundColor Red
    Write-Host "  seat, Excel and somebody logged in - it is the only machine whose" -ForegroundColor Red
    Write-Host "  checkout the engine runs from." -ForegroundColor Red
    Write-Host "  Nothing has been stopped." -ForegroundColor Green
    Write-Host ""
    exit 2
}

# -- 1. PULL, IF ASKED, AND BEFORE ANYTHING IS STOPPED --------------------------------
function Get-Git {
    $exe = (Get-Command git -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        foreach ($cand in @("C:\Program Files\Git\cmd\git.exe",
                            "C:\Program Files (x86)\Git\cmd\git.exe")) {
            if (Test-Path -LiteralPath $cand) { return $cand }
        }
    }
    return $exe
}

$git = Get-Git
if ($Pull) {
    if (-not $git) {
        Write-Host "  -Pull was asked for and git is not on this machine." -ForegroundColor Red
        Write-Host "  Nothing has been stopped." -ForegroundColor Green
        exit 3
    }
    # A DIRTY TREE IS A DECISION, NOT AN OBSTACLE TO ROUTE AROUND. Local edits are
    # somebody's work; this script will not merge over them, stash them or discard them.
    # It says what is uncommitted and stops, because losing an afternoon of somebody's
    # edits to a convenience flag is worse than the afternoon this script saves.
    $prevEA = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $dirty = & $git -C $Root status --porcelain --untracked-files=no 2>$null
    $ErrorActionPreference = $prevEA
    if ($dirty) {
        Write-Host ""
        Write-Host "  STOP. This checkout has uncommitted changes to tracked files:" -ForegroundColor Red
        $dirty -split "`n" | Where-Object { $_ } | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
        Write-Host ""
        Write-Host "  A pull would merge over somebody's work. Commit it, stash it, or" -ForegroundColor Yellow
        Write-Host "  discard it deliberately - then run this again." -ForegroundColor Yellow
        Write-Host "  Nothing has been stopped." -ForegroundColor Green
        Write-Host ""
        exit 4
    }
    Write-Host "  pulling..."
    $prevEA = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $git -C $Root pull --ff-only
    $pulled = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prevEA
    if (-not $pulled) {
        Write-Host "  The pull did not succeed. Nothing has been stopped." -ForegroundColor Red
        exit 5
    }
}

# -- 2. STOP THE TASK, IF THERE IS ONE ------------------------------------------------
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    if ($task.State -eq "Running") {
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Write-Host "  stopped the scheduled task '$TaskName'"
    } else {
        Write-Host "  the scheduled task '$TaskName' was not running"
    }
} else {
    Write-Host "  no scheduled task installed - install-runner-task.ps1 sets one up" -ForegroundColor Yellow
}

# -- 3. END WHATEVER IS ACTUALLY RUNNING ----------------------------------------------
#
# The step the obvious restart misses. Named before it is ended: a pid and a start time is
# what tells you afterwards whether you stopped the thing you meant to.
#
# PYTHONW.EXE TOO, AND CHECKED AFTERWARDS. On 23 September 2026 this printed "ending pid
# 41104" and the heartbeat on 8071 kept advertising pid 41104, build b4b4afa, started 19:21
# the day before. Two faults. It looked only for python.exe, while the task starts the
# runner windowless as pythonw.exe - the very name step 6 below already searches for. And
# Stop-Process ran with SilentlyContinue and was never checked, so a refusal (a process
# owned by another user or an elevated session) read as success. A kill is now confirmed
# by looking again, and a survivor stops the restart: starting a second runner beside it
# is the one outcome worse than doing nothing.
$restartAt = Get-Date
Start-Sleep -Seconds 1
function Get-RunnerProcs {
    @(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" `
          -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -like '*sdi_estimate_runner*' })
}
# GET-CIMINSTANCE ALREADY HANDS BACK A DATETIME. The WMI-string converter threw on it, the
# catch returned nothing, and the "born after the restart" test below could therefore never
# pass: on 23 Sep 2026 it waited 45 seconds and declared NO RUNNER beside a healthy one.
function Get-Started($p) {
    if ($p.CreationDate -is [DateTime]) { return $p.CreationDate }
    try { return [Management.ManagementDateTimeConverter]::ToDateTime($p.CreationDate) } catch { return $null }
}
$procs = Get-RunnerProcs
if ($procs.Count -eq 0) {
    Write-Host "  no runner process was left running"
} else {
    foreach ($p in $procs) {
        $st = Get-Started $p
        $started = if ($st) { $st.ToString("dd MMM HH:mm:ss") } else { "unknown" }
        Write-Host "  ending pid $($p.ProcessId) $($p.Name) (started $started)" -ForegroundColor Yellow
        try {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop
        } catch {
            Write-Host "    refused: $($_.Exception.Message)" -ForegroundColor Red
        }
    }
    Start-Sleep -Seconds 2
    $left = Get-RunnerProcs
    if ($left.Count -gt 0) {
        Write-Host ""
        Write-Host "  STOP. These runner processes are STILL RUNNING after being ended:" -ForegroundColor Red
        foreach ($p in $left) {
            $st = Get-Started $p
            Write-Host "    pid $($p.ProcessId) $($p.Name) started $(if ($st) { $st.ToString('dd MMM HH:mm:ss') } else { '?' })" -ForegroundColor Red
        }
        Write-Host "  Usually this means they belong to another user or an elevated session." -ForegroundColor Yellow
        Write-Host "  Open PowerShell as Administrator and run this script again." -ForegroundColor Yellow
        Write-Host "  Nothing has been started - a second runner beside a stale one is worse." -ForegroundColor Green
        exit 7
    }
}

# -- 4. THE STALE BYTECODE CASE, ONLY WHEN ASKED --------------------------------------
if ($Clean) {
    $caches = @(Get-ChildItem -Path $Root -Filter "__pycache__" -Recurse -Directory -ErrorAction SilentlyContinue)
    foreach ($c in $caches) { Remove-Item -LiteralPath $c.FullName -Recurse -Force -ErrorAction SilentlyContinue }
    Write-Host "  removed $($caches.Count) __pycache__ folder(s) - the next import is slower and correct"
}

if ($StopOnly) {
    Write-Host "  stopped. Nothing restarted (-StopOnly)." -ForegroundColor Green
    exit 0
}

# -- 5. START IT AGAIN ------------------------------------------------------------------
if ($task) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "  started the scheduled task"
} else {
    # No task: start a window the way a person would, so the runner keeps its interactive
    # desktop session. COM needs one - see install-runner-task.ps1 for why a Windows
    # service cannot do this job at all.
    $starter = Join-Path $Root "tools\start\start-runner.ps1"
    Start-Process -FilePath "powershell.exe" `
                  -ArgumentList @("-NoExit", "-ExecutionPolicy", "Bypass", "-File", $starter)
    Write-Host "  started a runner window - leave it open"
}

# -- 6. SAY WHAT IT WILL NOW RUN --------------------------------------------------------
#
# "It restarted" and "it is running the code you meant" are different claims and only the
# second one matters. This is the line that would have ended 401912-02's afternoon on the
# first run instead of the fourth.
#
# WAIT FOR IT, DO NOT GUESS AT IT. This slept 3 seconds and then declared the runner dead.
# On 22 September 2026 it said "NO RUNNER IS RUNNING. It was stopped and did not come back"
# twice, and both times the runner the task had started appeared a few seconds later - the
# task was working and the check was impatient. The person was told to start one by hand,
# did, and was refused by the one-runner lock because the "missing" runner was already up.
# A false alarm here costs more than a slow start: it sends someone to fix a thing that is
# not broken. So it now watches for up to 45 seconds and reports as soon as one appears.
$now = @()
$waited = 0
while ($waited -lt 45) {
    Start-Sleep -Seconds 3
    $waited += 3
    # ONLY A PROCESS BORN AFTER THE RESTART COUNTS. Counting any runner meant a survivor
    # satisfied this check on its first look and the restart was reported as done.
    $now = @(Get-RunnerProcs | Where-Object {
                 $st = Get-Started $_
                 $st -and $st -ge $restartAt })
    if ($now.Count -gt 0) { break }
    Write-Host "  waiting for the runner to start ($waited s)..." -ForegroundColor DarkGray
}
if ($now.Count -eq 0) {
    Write-Host ""
    Write-Host "  NO RUNNER IS RUNNING after $waited seconds. It was stopped and did not come back." -ForegroundColor Red
    Write-Host "  Start one by hand and read the window:" -ForegroundColor Yellow
    Write-Host "      .\tools\start\start-runner.ps1" -ForegroundColor Yellow
    exit 6
}

# ONE RUNNER IS A LAUNCHER AND ITS CHILD. The venv python(w).exe starts the base
# interpreter as a child with the same command line, so a healthy restart shows two pids
# born in the same second. On 24 Sep 2026 that was read as two runners (61184 and 53776
# at 11:08:00). A runner is a process whose parent is not itself a runner process; only
# two of THOSE is a second engine.
$settle = 0
do {
    Start-Sleep -Seconds 2
    $settle += 2
    $now = @(Get-RunnerProcs | Where-Object { $st = Get-Started $_; $st -and $st -ge $restartAt })
    $ids = @($now | ForEach-Object { $_.ProcessId })
    $roots = @($now | Where-Object { $ids -notcontains $_.ParentProcessId })
} while ($settle -lt 6)
foreach ($r in $roots) {
    $st = Get-Started $r
    $kids = @($now | Where-Object { $_.ParentProcessId -eq $r.ProcessId })
    if ($kids.Count -gt 0) {
        Write-Host "  new runner: pid $($kids[0].ProcessId) $($kids[0].Name) started $($st.ToString('HH:mm:ss')) (venv launcher pid $($r.ProcessId) - the same runner)" -ForegroundColor Green
    } else {
        Write-Host "  new runner: pid $($r.ProcessId) $($r.Name) started $($st.ToString('HH:mm:ss'))" -ForegroundColor Green
    }
}
if ($roots.Count -gt 1) {
    Write-Host ""
    Write-Host "  STOP. $($roots.Count) SEPARATE RUNNERS STARTED - not a launcher and its child." -ForegroundColor Red
    Write-Host "  Something besides the scheduled task is starting one (a startup shortcut," -ForegroundColor Yellow
    Write-Host "  a second task, an open start-runner window). Run this with -StopOnly," -ForegroundColor Yellow
    Write-Host "  remove the extra starter, then run it again." -ForegroundColor Yellow
    exit 8
}

if ($git) {
    $prevEA = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $sha    = (& $git -C $Root rev-parse --short=7 HEAD 2>$null)
    $subj   = (& $git -C $Root log -1 --format=%s 2>$null)
    $behind = (& $git -C $Root rev-list --count "HEAD..@{u}" 2>$null)
    $ErrorActionPreference = $prevEA
    Write-Host ""
    Write-Host "  the engine will run $("$sha".Trim()) - $("$subj".Trim())" -ForegroundColor Green
    if ("$behind".Trim() -and "$behind".Trim() -ne "0") {
        Write-Host ""
        Write-Host "  BUT THIS CHECKOUT IS $("$behind".Trim()) COMMIT(S) BEHIND ITS BRANCH." -ForegroundColor Red
        Write-Host "  Re-run with -Pull, or pull by hand and run this again." -ForegroundColor Red
        Write-Host "  (Read from the last fetch, so the real gap may be larger.)" -ForegroundColor Yellow
    }
}

# -- 7. ASK THE SERVICE, DO NOT ASK THE READER TO ----------------------------------------
#
# The pass the reviewer asks for before every job - online 1, process_count 1, conflict
# false, build = HEAD with no +local edits - was a command typed by hand after every
# restart. It is the only proof the job will run on this commit, so this script asks it.
if (-not $Service) {
    if ($env:SDI_SERVICE_URL) { $Service = $env:SDI_SERVICE_URL }
    elseif ($env:SDI_PORT)    { $Service = "http://localhost:$($env:SDI_PORT)" }
    else                      { $Service = "http://localhost:8071" }
}
$Service = ($Service -split ",")[0].TrimEnd("/")
$headSha = if ($git) { "$sha".Trim() } else { "" }
$hdr = @{}
if ($ApiKey) { $hdr["X-SDI-Key"] = $ApiKey }
$mine = $null
$resp = $null
$asked = 0
Write-Host ""
Write-Host "  asking $Service which runner it sees..."
while ($asked -lt 90) {
    try {
        $resp = Invoke-RestMethod -Uri "$Service/api/estimate/runners" -Headers $hdr -TimeoutSec 10
        $mine = @($resp.runners | Where-Object { $_.online -and "$($_.hostname)" -ieq $me }) | Select-Object -First 1
        if ($mine -and $headSha -and "$($mine.build)".StartsWith($headSha)) { break }
    } catch {
        $resp = $null
    }
    Start-Sleep -Seconds 5
    $asked += 5
}
if (-not $resp) {
    Write-Host "  COULD NOT CONFIRM: $Service did not answer /api/estimate/runners." -ForegroundColor Red
    Write-Host "  Is the service up, and is -Service (or SDI_SERVICE_URL) the portal this runner reports to?" -ForegroundColor Yellow
    exit 10
}
$fails = @()
if (-not $mine)                                   { $fails += "the service sees no online runner from $me" }
else {
    if ([int]$resp.online -ne 1)                  { $fails += "online is $($resp.online), not 1" }
    if ($mine.process_count -ne 1)                { $fails += "process_count is $(if ($null -eq $mine.process_count) { 'unknown' } else { $mine.process_count }), not 1" }
    if ($mine.conflict)                           { $fails += "conflict is true - two processes are claiming work" }
    if ($headSha -and -not "$($mine.build)".StartsWith($headSha)) { $fails += "build is '$($mine.build)', HEAD is $headSha" }
    if ("$($mine.build)" -like "*+local edits*")  { $fails += "build carries +local edits" }
}
if ($fails.Count -gt 0) {
    Write-Host ""
    Write-Host "  FAIL - do not run a job yet:" -ForegroundColor Red
    foreach ($f in $fails) { Write-Host "    - $f" -ForegroundColor Red }
    exit 9
}
Write-Host "  PASS - $Service sees one runner on $me, one process, no conflict, build $($mine.build)" -ForegroundColor Green
Write-Host ""
Write-Host "  Check the next job's first lines say that same commit, with no '+local" -ForegroundColor Cyan
Write-Host "  edits', before you read a single number." -ForegroundColor Cyan
