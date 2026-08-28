<#
    Start the SDI Intelligence service.

        .\tools\start\start-service.ps1
        .\tools\start\start-service.ps1 -Port 8071
        .\tools\start\start-service.ps1 -Force

    WHY THIS EXISTS. The port is read from $env:SDI_PORT, and a PowerShell
    environment variable belongs to ONE WINDOW. Set it, open a second window for
    the runner, come back after lunch, and app.py falls back to config.py's
    default of 8071 and collides with whatever already holds it. The error names
    the port and nothing else, so it reads as "something is broken" rather than
    "this window never knew which port you meant".

    ASCII ONLY, DELIBERATELY. Windows PowerShell 5.1 reads a .ps1 in the system
    codepage unless the file carries a byte-order mark, so a single em dash in a
    comment arrives as three bytes of nonsense, terminates a string early, and
    produces a parse error pointing at a line thirty below the real one. Keeping
    to ASCII means the encoding cannot matter.
#>
[CmdletBinding()]
param(
    [int]    $Port = 8072,
    [string] $Root = "",
    [switch] $Force,
    # WRITE EVERYTHING TO A FILE AS WELL AS THE CONSOLE.
    #
    # Used by the scheduled task, which runs with no window at all: without this a service
    # that dies at 3pm leaves nothing behind but a page that stopped answering, and the only
    # honest thing anybody can say afterwards is "it was working this morning". Off by
    # default because a console session already has its output on screen, and piping through
    # Tee-Object is not worth the buffering when somebody is watching it live.
    [switch] $Log
)

$ErrorActionPreference = "Stop"

# -- WHERE THIS SCRIPT IS, ASKED IN THE BODY AND NOT IN A PARAMETER DEFAULT ----------
#
# $PSScriptRoot is EMPTY inside param() under `powershell -File`, so "$PSScriptRoot\..\.."
# becomes "\..\.." - a ROOT-RELATIVE path - and Resolve-Path turns it into C:\. The script
# then looked for the virtualenv at C:\.venv\Scripts\python.exe and threw. It worked when
# invoked as .\tools\start\<script>.ps1 and failed under -File, which is a difference
# nobody should have to know about to start a runner.
#
# All three scripts in this folder carried the identical line. Two survived only because
# nobody had typed them the other way yet.
#
# Two fallbacks, then a refusal that names what it resolved to. A path silently one level
# wrong is exactly how this failed: the error named C:\.venv and nothing said why.
if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) {
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if (-not $here) {
        throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision explicitly."
    }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}


# -- ASKED IN THE BODY, NOT IN A PARAMETER DEFAULT -----------------------------------
# $PSScriptRoot is empty inside param() under `powershell -File`, so "$PSScriptRoot\..\.."
# becomes "\..\.." - root-relative - and resolves to C:\. All three scripts in this folder
# carried the same line; install-runner-task.ps1 is the one that was invoked that way and
# went looking for a virtualenv at C:\.venv. A default that is right depending on how
# somebody typed the command is not a default.
if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) {
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if (-not $here) { throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision" }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}
$python = Join-Path $Root "sdi-intelligence-backend\.venv\Scripts\python.exe"
$app    = Join-Path $Root "sdi-intelligence-backend\app.py"

if (-not (Test-Path $python)) { throw "No service virtualenv at $python" }
if (-not (Test-Path $app))    { throw "No app.py at $app" }

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


# -- STAMP THE BUILD, FROM THE SHELL RATHER THAN FROM THE SERVICE ----------------------
#
# app.py resolves its own commit by shelling out to git, and on SDI-APP01 that came back
# "unknown" on a service that was perfectly current. git works there for a person and not
# for the account the task runs as - a different PATH, or safe.directory refusing a repo
# somebody else cloned. Either way the one field that exists to catch a stale deployment
# was the field that stopped working, which is the worst place for it to fail.
#
# Resolving it HERE and handing it down closes that: this script is the task's own action,
# so whatever it can see, the service gets. SDI_COMMIT is checked before git by app.py, so
# nothing else needs to change.
#
# NOT hardcoded in .env, which was the other option and is worse than "unknown": a pinned
# hash keeps reporting a build that stopped running at the next deploy, and reports it
# confidently. A wrong answer here costs an afternoon; an absent one costs a question.
if (-not $env:SDI_COMMIT) {
    # ONE RESOLVER, USED TWICE. This block used to repeat the git lookup inline, and
    # the copy below it drifted: only one of the two ever learned to read .sdi-commit,
    # so a machine without git got a build number from one path and "unknown" from
    # the other depending on which ran.
    $resolved = Get-HeadCommit $Root
    if ($resolved) { $env:SDI_COMMIT = $resolved }
    if ($env:SDI_COMMIT) {
        Write-Host "  build $($env:SDI_COMMIT)" -ForegroundColor DarkGray
    } else {
        Write-Host "  build unresolved - the site will report 'unknown'" -ForegroundColor Yellow
    }
}

# SAY WHO HAS THE PORT, not just that somebody does. "Only one usage of each
# socket address" sends you to the firewall. A name, a pid and the account it
# runs as sends you to the right window - which is how we established that 8071
# was LocalSystem and had no rights on the CAD share.
$held = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($held.Count -gt 0) {
    $pids = @($held | Select-Object -ExpandProperty OwningProcess -Unique)
    $owners = foreach ($procId in $pids) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        $ci   = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
        $who  = "unknown"
        if ($ci) {
            $owner = Invoke-CimMethod -InputObject $ci -MethodName GetOwner -ErrorAction SilentlyContinue
            if ($owner -and $owner.User) { $who = "$($owner.Domain)\$($owner.User)" }
        }
        $started = "unknown"
        if ($proc -and $proc.StartTime) { $started = $proc.StartTime.ToString("HH:mm:ss") }
        # Hoisted out of the hashtable rather than written inline. An if used as
        # an expression inside a literal is the kind of thing that works in one
        # PowerShell and not another, and this file has already cost an evening.
        $name = "gone"
        if ($proc) { $name = $proc.ProcessName }

        [pscustomobject]@{
            PID     = $procId
            Name    = $name
            RunAs   = $who
            Started = $started
        }
    }

    if ($Force) {
        Write-Host "Port $Port is in use. Stopping:" -ForegroundColor Yellow
        $owners | Format-Table -AutoSize | Out-String | Write-Host
        foreach ($procId in $pids) { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Milliseconds 700
    } else {
        Write-Host "Port $Port is already in use by:" -ForegroundColor Red
        $owners | Format-Table -AutoSize | Out-String | Write-Host
        Write-Host "Re-run with -Force to stop it, or choose another port:" -ForegroundColor Yellow
        Write-Host "    .\tools\start\start-service.ps1 -Port 8073" -ForegroundColor Yellow
        exit 1
    }
}

# Set HERE, so this window cannot disagree with itself about which port it meant.
$env:SDI_PORT = "$Port"


# STAMP THE COMMIT THE SERVICE IS ABOUT TO RUN, resolved HERE where git is on the PATH.
#
# The service reports its own version as X-SDI-Commit on every response, so "which code is
# actually running?" is one curl rather than an investigation. It resolves that by running git
# in its own directory -- and the service starts from a virtualenv whose PATH has no git, so it
# answered "unknown" and the header could not do the one job it exists for. An afternoon was
# spent on a stale process that a truthful header would have identified in a line: the service
# was serving code from before a pull, the page (static HTML) was serving code from after it,
# and the two disagreeing looked like a broken feature rather than a process that needed
# restarting.
#
# This shell HAS git. Resolve it here and hand it over, so the answer is always the truth about
# the code on disk at the moment of starting. SDI_COMMIT already takes precedence in the
# resolver precisely for deploys that cannot reach git.
$commit = Get-HeadCommit $Root
if ($commit) {
    $env:SDI_COMMIT = $commit
} else {
    # Never leave a STALE value from a previous run in this window standing in for the truth.
    Remove-Item Env:\SDI_COMMIT -ErrorAction SilentlyContinue
    Write-Host "git could not name the commit here - /api/health will report 'unknown'." -ForegroundColor Yellow
}



Write-Host "SDI Intelligence service" -ForegroundColor Cyan
Write-Host "    http://localhost:$Port/estimating" -ForegroundColor Cyan
if ($env:SDI_COMMIT) {
    # RESTARTED IS NOT THE SAME AS RELOADED, and this line is where that becomes visible. A
    # pull changes files on disk; a running service goes on serving what it imported at start.
    Write-Host "    running commit $($env:SDI_COMMIT)  (after a git pull, restart this window)" -ForegroundColor DarkGray
}
Write-Host "Ctrl+C to stop."
Write-Host ""

# THE SECOND WINDOW IS THE ONE PEOPLE FORGET. This service queues estimates; it
# does not run them. Without a runner the page is correct and useless, and the
# reason is on a screen nobody is looking at. So say it here, where somebody is.
Write-Host "This service QUEUES estimates. It does not run them." -ForegroundColor Yellow
Write-Host "In a second window, start the runner on a machine with SOLIDWORKS:" -ForegroundColor Yellow
Write-Host "    C:\ClaudeVision\tools\start\start-runner.ps1 -Server http://localhost:$Port" -ForegroundColor Yellow
Write-Host ""

if ($Log) {
    $logDir = Join-Path $Root "output\logs"
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $logFile = Join-Path $logDir ("service-" + (Get-Date -Format "yyyy-MM-dd") + ".log")
    Write-Host "Logging to $logFile"
    "==== started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') on port $Port, commit $($env:SDI_COMMIT) ====" |
        Out-File -FilePath $logFile -Append -Encoding utf8

    # THE SERVICE WAS KILLED BY ITS OWN FIRST LINE OF OUTPUT.
    #
    # In Windows PowerShell 5.1, `& native 2>&1` while $ErrorActionPreference is "Stop" turns
    # the first stderr line into a TERMINATING error. uvicorn writes its startup banner -
    # "INFO: Started server process" - to stderr, so the redirection added here for logging
    # made the script throw the instant the service began to talk. The log showed a "started"
    # stamp, no output, and no "exited" stamp; the task went straight back to Ready and every
    # page returned ERR_CONNECTION_REFUSED. Logging the service is what stopped it running.
    #
    # Stderr is NORMAL OUTPUT from this process, not an error condition, so the preference is
    # dropped for the one statement that treats it as such - and restored in a finally, with
    # the exit stamp, so a crash still leaves the record this whole switch exists to produce.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $python $app 2>&1 | Tee-Object -FilePath $logFile -Append
    } finally {
        $ErrorActionPreference = $prev
        "==== exited  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') with code $LASTEXITCODE ====" |
            Out-File -FilePath $logFile -Append -Encoding utf8
    }
} else {
    & $python $app
}
