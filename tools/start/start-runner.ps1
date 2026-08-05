<#
    Start the SDI Estimating Intelligence runner.

        .\tools\start\start-runner.ps1                             # localhost:8072
        .\tools\start\start-runner.ps1 -Server http://10.0.0.5:8071  # the server

    The runner executes estimates on THIS machine, which is why it has to be a
    machine with a SOLIDWORKS seat, Office, and somebody logged in. It dials out
    to the service and is never connected to, so it does not matter where this
    machine is or what address it has today.

    Leave the window open. Closing it stops the runner, the service notices
    within a minute and a half, and the page goes red — which is correct, but is
    a confusing thing to discover by accident.
#>
[CmdletBinding()]
param(
    [string] $Server = "http://localhost:8072",
    [string] $Root   = (Resolve-Path "$PSScriptRoot\..\.."),
    [string] $ApiKey = $env:SDI_API_KEY
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Root ".venv\Scripts\python.exe"     # the ENGINE's venv — it runs the engine
$runner = Join-Path $Root "tools\runner\sdi_estimate_runner.py"

if (-not (Test-Path $python)) { throw "No engine virtualenv at $python" }
if (-not (Test-Path $runner)) { throw "No runner at $runner — merge the branch first" }

$env:SDI_SERVER = $Server
if ($ApiKey) { $env:SDI_API_KEY = $ApiKey }

Write-Host "SDI estimating runner  ·  serving $Server" -ForegroundColor Cyan
Write-Host "Leave this window open. Ctrl+C to stop.`n"
& $python $runner
