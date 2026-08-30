<#
    Point an NSSM-supervised SDI Intelligence service at start-service.ps1.

        .\tools\start\configure-nssm-service.ps1
        .\tools\start\configure-nssm-service.ps1 -Port 8071 -ServiceName SDIIntelligence
        .\tools\start\configure-nssm-service.ps1 -Show          # report, change nothing

    WHY THIS EXISTS.

    SDI-APP01 runs the portal as an NSSM service whose Application is uvicorn.exe:

        uvicorn.exe app:app --host 0.0.0.0 --port 8071

    That works, and it skips start-service.ps1 entirely. So the machine ends up with TWO ways
    of starting the same service - the laptop's, which does the setup, and the server's, which
    does not - and everything start-service.ps1 arranges is simply absent on the server. Two
    symptoms, one cause:

      * /api/health reports  commit: unknown.  app.py resolves its own commit by shelling out
        to git, and the service's PATH has no git (and the account may not own the clone, so
        safe.directory refuses it anyway). start-service.ps1 already solves this: it runs in a
        shell that CAN see git, resolves the hash, and hands it down through SDI_COMMIT. On
        8071 that code never runs. The one field that exists to catch a stale deployment is
        therefore the field that stopped working - which is the worst place for it to fail,
        because the failure looks like a working service.

      * SDI_ENGINE_PYTHON is unset, so parity and the estimator override fall back to
        <root>\.venv\Scripts\python.exe. On the server the interpreter is somewhere else, so
        those routes answer "Engine python not found".

    WHAT THIS DOES NOT DO, AND IT IS THE IMPORTANT ONE: it does not pin SDI_COMMIT into
    AppEnvironmentExtra. A pinned hash is WORSE than "unknown". "Unknown" costs a question; a
    hash that stopped being true at the next deploy is a confident wrong answer, and it will be
    believed. The same reasoning is already recorded against putting SDI_COMMIT in .env, and
    tests assert it is not there. Resolving it at every start is the only version of this that
    stays true.

    SDI_ENGINE_PYTHON is different and IS set here: it is a fixed path on a fixed machine, so
    pinning it says something that remains true.

    ASCII ONLY, like the other scripts here - Windows PowerShell 5.1 reads a .ps1 in the system
    codepage unless the file carries a BOM, and one stray dash becomes a parse error pointing
    thirty lines from the real one.
#>
[CmdletBinding()]
param(
    [string] $ServiceName  = "SDIIntelligence",
    [int]    $Port         = 8071,
    [string] $Root         = "",
    [string] $EnginePython = "",
    [string] $NssmExe      = "",
    [switch] $Show
)

$ErrorActionPreference = "Stop"

# -- WHERE THIS SCRIPT IS, asked in the body: $PSScriptRoot is EMPTY inside param() under
# `powershell -File`, so a default of "$PSScriptRoot\..\.." resolves to C:\.
if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) {
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}

$startScript = Join-Path $Root "tools\start\start-service.ps1"
if (-not (Test-Path $startScript)) {
    throw "start-service.ps1 not found at $startScript - is -Root right? ($Root)"
}

# -- FIND NSSM ------------------------------------------------------------------------
if (-not $NssmExe) {
    $cmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($cmd) { $NssmExe = $cmd.Source }
}
if (-not $NssmExe) {
    foreach ($cand in @("C:\tools\nssm-2.24\win64\nssm.exe",
                        "C:\tools\nssm\win64\nssm.exe",
                        "C:\nssm\win64\nssm.exe")) {
        if (Test-Path $cand) { $NssmExe = $cand; break }
    }
}
if (-not $NssmExe) {
    throw "nssm.exe not found. Pass -NssmExe <path>, or see SDI-Intelligence-WindowsService.ps1 which installs it."
}

function Get-NssmValue([string] $key) {
    # NSSM writes UTF-16 with trailing nulls; strip them or every comparison fails.
    $raw = (& $NssmExe get $ServiceName $key 2>&1) -join "`n"
    return ($raw -replace "`0", "").Trim()
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    throw "There is no service called '$ServiceName' on this machine. Pass -ServiceName, or install it first."
}

Write-Host ""
Write-Host "Service '$ServiceName' as it stands" -ForegroundColor Cyan
Write-Host "  state       : $($svc.Status)"
Write-Host "  application : $(Get-NssmValue 'Application')"
Write-Host "  parameters  : $(Get-NssmValue 'AppParameters')"
Write-Host "  directory   : $(Get-NssmValue 'AppDirectory')"
Write-Host "  environment : $(Get-NssmValue 'AppEnvironmentExtra')"
Write-Host ""

if ($Show) {
    Write-Host "-Show given: nothing changed." -ForegroundColor DarkGray
    return
}

# -- THE ENGINE INTERPRETER -----------------------------------------------------------
# Looked for rather than assumed, and NAMED when it cannot be found. Setting
# SDI_ENGINE_PYTHON to a path that does not exist just moves the same error later.
if (-not $EnginePython) {
    foreach ($cand in @((Join-Path $Root ".venv\Scripts\python.exe"),
                        (Join-Path $Root "sdi-intelligence-backend\.venv\Scripts\python.exe"))) {
        if (Test-Path $cand) { $EnginePython = $cand; break }
    }
}
if ($EnginePython -and -not (Test-Path $EnginePython)) {
    throw "SDI_ENGINE_PYTHON was given as $EnginePython, which does not exist on this machine."
}
if (-not $EnginePython) {
    Write-Host "No engine interpreter found under $Root." -ForegroundColor Yellow
    Write-Host "  Parity and the estimator override will keep answering 'Engine python not found'." -ForegroundColor Yellow
    Write-Host "  Re-run with -EnginePython <full path to python.exe> once the engine venv exists." -ForegroundColor Yellow
    Write-Host ""
}

# -- RECONFIGURE ----------------------------------------------------------------------
$psExe = (Get-Command powershell.exe).Source
$params = "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`" -Port $Port -Log"

Write-Host "Reconfiguring to start through start-service.ps1" -ForegroundColor Cyan
& $NssmExe set $ServiceName Application    $psExe    | Out-Null
& $NssmExe set $ServiceName AppParameters  $params   | Out-Null
& $NssmExe set $ServiceName AppDirectory   $Root     | Out-Null

if ($EnginePython) {
    # ONE variable, deliberately. AppEnvironmentExtra REPLACES the whole block, so listing only
    # what belongs here is also what stops this script quietly dropping something set by hand.
    # SDI_COMMIT is NOT among these - see the header.
    & $NssmExe set $ServiceName AppEnvironmentExtra "SDI_ENGINE_PYTHON=$EnginePython" | Out-Null
    Write-Host "  SDI_ENGINE_PYTHON = $EnginePython" -ForegroundColor DarkGray
}

Write-Host "  application       = $psExe" -ForegroundColor DarkGray
Write-Host "  parameters        = $params" -ForegroundColor DarkGray
Write-Host ""

Write-Host "Restarting..." -ForegroundColor Cyan
& $NssmExe restart $ServiceName | Out-Null
Start-Sleep -Seconds 6

# -- VERIFY, because a service that starts is not a service that is serving -------------
try {
    $health = Invoke-RestMethod "http://localhost:$Port/api/health" -TimeoutSec 15
    $commit = $health.commit
    if ($commit -and $commit -ne "unknown") {
        Write-Host "Serving commit $commit on port $Port." -ForegroundColor Green
    } else {
        Write-Host "The service is up but still reports commit 'unknown'." -ForegroundColor Yellow
        Write-Host "  git is not reachable from the service account either. Check:" -ForegroundColor Yellow
        Write-Host "    git -C $Root rev-parse --short HEAD" -ForegroundColor Yellow
        Write-Host "  run as the account the service uses, and look for a safe.directory refusal." -ForegroundColor Yellow
    }
} catch {
    Write-Host "The service did not answer on port $Port." -ForegroundColor Red
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  NSSM captures the script's own output - check its stdout/stderr files:" -ForegroundColor Yellow
    Write-Host "    $NssmExe get $ServiceName AppStdout" -ForegroundColor Yellow
    Write-Host "  To put it back the way it was:" -ForegroundColor Yellow
    Write-Host "    $NssmExe set $ServiceName Application <the uvicorn.exe path shown above>" -ForegroundColor Yellow
    Write-Host "    $NssmExe set $ServiceName AppParameters <the parameters shown above>" -ForegroundColor Yellow
}
Write-Host ""
