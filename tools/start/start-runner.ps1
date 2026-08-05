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

    ASCII ONLY. See start-service.ps1 for why.
#>
[CmdletBinding()]
param(
    [string] $Server = "http://localhost:8072",
    [string] $Root   = (Resolve-Path "$PSScriptRoot\..\.."),
    [string] $ApiKey = $env:SDI_API_KEY
)

$ErrorActionPreference = "Stop"
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
