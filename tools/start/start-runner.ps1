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

    WHICH PORT. There are two services and this script used to guess wrong.
    config.py defaults to 8071 and that is what the installed Windows service
    listens on, which is the page people actually open. start-service.ps1
    defaults to 8072 on purpose, because 8071 is already held by that service -
    it is the port for a hand-started copy while the real one keeps running.

    This defaulted to 8072, so a runner started with no arguments dialled the
    hand-started service while the page on 8071 said "No runner connected -
    estimates cannot be run", and stayed saying it. Nothing was broken and
    nothing said what was wrong: two defaults for one number, and the runner
    holding the one that was not the page's.

    It now defaults to the SAME 8071 config.py does, so the default agrees with
    the default. Pass -Server explicitly when serving the hand-started copy.

    ASCII ONLY. See start-service.ps1 for why.
#>
[CmdletBinding()]
param(
    # ONE DEFAULT, THE SERVICE'S OWN. SDI_PORT first, so a window that already
    # knows the port is believed; then 8071, which is config.py's default and
    # the installed service's port. Never a literal that only this file knows.
    [string] $Server = ("http://localhost:" + $(if ($env:SDI_PORT) { $env:SDI_PORT } else { "8071" })),
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

$env:SDI_SERVER = $Server
if ($ApiKey) { $env:SDI_API_KEY = $ApiKey }

Write-Host "SDI estimating runner" -ForegroundColor Cyan
Write-Host "    serving $Server" -ForegroundColor Cyan
Write-Host "Leave this window open. Ctrl+C to stop."
Write-Host ""
& $python $runner
