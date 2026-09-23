<#
    Start the SDI Estimating Intelligence runner.

        .\tools\start\start-runner.ps1
        .\tools\start\start-runner.ps1 -Server http://10.0.0.5:8071

    The runner executes estimates on THIS machine, which is why it has to be a
    machine with a SOLIDWORKS seat, Office, and somebody logged in. It dials out
    to the service and is never connected to, so it does not matter where this
    machine is or what address it has today.

    Leave the window open. Closing it stops the runner, the service notices
    within a minute and a half, and the page goes red - which is correct, but is
    a confusing thing to discover by accident.

    WHICH PORT. This does not guess any more, because guessing has now been wrong
    in BOTH directions.

    There are two services: the installed Windows service on 8071, and a
    hand-started copy on 8072 - deliberately different, so a hand-started one can
    run without stopping the installed one. This script first defaulted to 8072,
    which dialled the hand-started service while the page on 8071 said "No runner
    connected"; it was changed to 8071, and then the Windows service was stopped
    for testing and the same failure happened the other way round. Both times the
    runner reported itself as running perfectly, polled a port with nothing on it,
    and nothing anywhere said what was wrong.

    So it now ASKS. With no -Server it probes SDI_PORT, 8071 and 8072, and serves
    the one that answers /api/health. When more than one answers it SAYS SO and takes
    SDI_PORT if set, otherwise 8071 - see the probe below for why. With an explicit -Server it probes that
    one and REFUSES TO START if nothing answers, rather than polling into
    silence. A runner that cannot reach its service is not a runner, and it should
    say so in the window you are looking at rather than on a page you are not.

    ASCII ONLY. See start-service.ps1 for why.
#>
[CmdletBinding()]
param(
    # EMPTY MEANS FIND IT. See the header: a hard-coded default has been wrong in both
    # directions, so the port is discovered rather than assumed. Pass -Server to pin it.
    [string] $Server = "",
    [string] $Root   = "",
    [string] $ApiKey = $env:SDI_API_KEY
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
# $PSScriptRoot is empty inside param() under some invocations, and "$PSScriptRoot\..\.."
# then becomes "\..\.." - a ROOT-RELATIVE path that resolves to C:\. This script worked
# because it is always run as .\tools\start\start-runner.ps1; its twin
# install-runner-task.ps1 was run once as `powershell -File ...` and looked for the
# virtualenv at C:\.venv\Scripts\python.exe. Same line, same latent fault, and the only
# difference was how somebody happened to type it.
if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) {
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if (-not $here) { throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision" }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}

$python = Join-Path $Root ".venv\Scripts\python.exe"     # the ENGINE venv - it runs the engine
$runner = Join-Path $Root "tools\runner\sdi_estimate_runner.py"

if (-not (Test-Path $python)) { throw "No engine virtualenv at $python" }
if (-not (Test-Path $runner)) { throw "No runner at $runner. Merge the branch first." }

# ASK WINDOWS DIRECTLY. This is the authoritative duplicate check, and it lives
# here rather than in the runner because a question asked here cannot break the
# process asking it. Two attempts at doing this with a file lock inside Python
# both ended by stopping the one runner that was wanted.
$all = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like '*sdi_estimate_runner*' -and $_.ProcessId -ne $PID })

# ONE RUNNER IS TWO PROCESSES. A virtualenv python.exe on Windows is a launcher
# that starts the BASE interpreter as a child, so a single healthy runner shows
# up twice - the .venv one and the Python3xx one - with identical command lines.
# Counting processes would report every runner as its own duplicate. Dropping
# any process whose parent is also a runner leaves one entry per actual launch.
$ids  = @($all | ForEach-Object { $_.ProcessId })
$mine = @($all | Where-Object { $ids -notcontains $_.ParentProcessId })

if ($mine.Count -gt 0) {
    Write-Host "A runner is already running on this machine:" -ForegroundColor Red
    Write-Host "  $($mine.Count) runner(s), $($all.Count) process(es) - a venv python starts the base one as a child." -ForegroundColor Red
    $all | Select-Object ProcessId, ParentProcessId, CommandLine | Format-Table -AutoSize -Wrap | Out-String | Write-Host
    Write-Host "One runner per machine: SOLIDWORKS and Excel are driven on one desktop." -ForegroundColor Yellow
    Write-Host "Stop them all with:" -ForegroundColor Yellow
    Write-Host "    Get-CimInstance Win32_Process -Filter ""Name='python.exe'"" |" -ForegroundColor Yellow
    Write-Host "      Where-Object CommandLine -like '*sdi_estimate_runner*' |" -ForegroundColor Yellow
    Write-Host "      ForEach-Object { Stop-Process -Id `$_.ProcessId -Force }" -ForegroundColor Yellow
    exit 1
}

# -- ASK WHICH SERVICE IS ACTUALLY THERE ---------------------------------------------
#
# A runner that cannot reach its service still starts, still prints a cheerful banner, and
# still polls - into nothing. The page then says "No runner connected" and the two facts sit
# in two windows with nothing joining them. So the reachability is settled HERE, before the
# banner, where somebody is looking.
function Test-SdiService([string] $Base) {
    try {
        $r = Invoke-WebRequest -Uri "$Base/api/health" -TimeoutSec 3 -UseBasicParsing `
                               -ErrorAction Stop
        return $r.StatusCode -eq 200
    } catch {
        # 401 means a service IS there and wants a key - that is reachable for this purpose.
        $code = $null
        try { $code = [int]$_.Exception.Response.StatusCode } catch { }
        return ($code -eq 401)
    }
}

if ($Server -and $Server.Contains(",")) {
    # A LIST IS SERVED AS A LIST. The runner asks each for work; one that is down is
    # reported once in the runner's own output and retried, so none is required here.
    Write-Host "  serving every service on the list: $Server" -ForegroundColor Green
} elseif ($Server) {
    if (-not (Test-SdiService $Server)) {
        Write-Host "Nothing is answering at $Server." -ForegroundColor Red
        Write-Host "  The runner would poll it for ever and the page would say" -ForegroundColor Yellow
        Write-Host "  'No runner connected' with nothing to explain why, so it stops here." -ForegroundColor Yellow
        Write-Host "  Start the service first:" -ForegroundColor Yellow
        Write-Host "      .\tools\start\start-service.ps1" -ForegroundColor Yellow
        Write-Host "  Or omit -Server and this will find whichever one is running." -ForegroundColor Yellow
        exit 1
    }
} else {
    # BOTH CAN ANSWER, AND THAT IS THE CASE THIS USED TO GET WRONG IN SILENCE.
    #
    # 22 September 2026: the page on 8071 said "No runner connected" while a healthy runner
    # sat on 8072, because this probed 8072 first and stopped at the first answer. Nothing
    # was broken - the runner and the page were on different services, and nothing said so.
    # Every candidate is now asked. One answer is used as before. More than one is SAID,
    # loudly, and the choice is made by rule rather than by probe order: SDI_PORT if it is
    # set and answering, otherwise 8071 - the installed service the portal is opened on.
    $candidates = @()
    if ($env:SDI_PORT) { $candidates += "http://localhost:$($env:SDI_PORT)" }
    $candidates += @("http://localhost:8071", "http://localhost:8072")
    $candidates = $candidates | Select-Object -Unique

    $answering = @()
    foreach ($c in $candidates) {
        Write-Host "  probing $c ..." -ForegroundColor DarkGray
        if (Test-SdiService $c) { $answering += $c }
    }
    # ALL OF THEM, NOT THE FIRST. Picking one is what left the other page saying "No runner
    # connected" beside a healthy runner, on 22 and 23 September. The runner takes a list.
    if ($answering.Count -ge 1) { $Server = ($answering -join ",") }
    if ($answering.Count -gt 1) {
        Write-Host ""
        Write-Host "  more than one service is running: this runner serves them all" -ForegroundColor Green
        Write-Host ""
    }
    if (-not $Server) {
        Write-Host "No SDI Intelligence service is answering." -ForegroundColor Red
        Write-Host "  Tried: $($candidates -join ', ')" -ForegroundColor Yellow
        Write-Host "  Start one in another window:" -ForegroundColor Yellow
        Write-Host "      .\tools\start\start-service.ps1" -ForegroundColor Yellow
        exit 1
    }
    Write-Host "  found the service at $Server" -ForegroundColor Green
}

$env:SDI_SERVER = $Server
if ($ApiKey) { $env:SDI_API_KEY = $ApiKey }

Write-Host "SDI estimating runner" -ForegroundColor Cyan
Write-Host "    serving $Server" -ForegroundColor Cyan
Write-Host "Leave this window open. Ctrl+C to stop."
Write-Host ""

# THE RUNNER WAS KILLED BY ITS OWN FIRST LINE OF OUTPUT.
#
# In Windows PowerShell 5.1 a native command's stderr is written into the ERROR stream as a
# NativeCommandError record, and under $ErrorActionPreference = "Stop" (set at the top of this
# script) that record is TERMINATING. Python's logging writes to stderr by default, so the
# runner died on the first line it logged:
#
#     python.exe : At C:\ClaudeVision\tools\start\start-runner.ps1:177 char:1
#     + & $python $runner ...
#         + CategoryInfo : NotSpecified: (...) [], RemoteException
#         + FullyQualifiedErrorId : NativeCommandError
#
# The window had already said "found the service at http://localhost:8072" and "serving" in
# green, so it read as a runner that had started and then crashed for its own reasons - when
# what killed it was this script treating normal output as a fault.
#
# start-service.ps1 has carried the fix for this since the service hit it: stderr is NORMAL
# OUTPUT from a Python process, not an error condition, so the preference is dropped for the
# one statement that treats it as such and restored afterwards. The runner never got it. It is
# the same bug, in the same shell, one file over.
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
try {
    & $python $runner
} finally {
    $ErrorActionPreference = $prev
}
