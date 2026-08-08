<#
    Run one job through the estimator.

        .\run-job.ps1 '<job folder>'
        .\run-job.ps1 '<job folder>' -Deliverables
        .\run-job.ps1 '<job folder>' -Twice        # reproducibility check

    Exists because a long command line pasted into a console loses its first character
    often enough to matter, and PowerShell then runs the fragment: "C:\ClaudeVision\..."
    arriving as ":\ClaudeVision\..." leaves a bare "r 42", which is Invoke-History, which
    silently re-runs whatever command 42 happened to be. Twice in one day that looked like
    the engine hanging when it was replaying an old run.

    -Twice runs the same pack through unchanged and prints both totals. Same code, same
    pack, same answer is the property the caches exist for, and nobody had actually
    measured it.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $Job,
    [switch] $Deliverables,
    [switch] $Twice
)

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$main   = Join-Path $root 'src\main.py'

if (-not (Test-Path $python)) { Write-Error "no virtualenv at $python"; exit 1 }
if (-not (Test-Path $Job))    { Write-Error "no such job folder: $Job"; exit 1 }

$estArgs = @($main, '--job', $Job, '--generate-ai-spreadsheet')
if ($Deliverables) { $estArgs += '--deliverables' }

function Invoke-Run([string] $label) {
    Write-Host "`n=== $label ===`n" -ForegroundColor Cyan
    & $python @estArgs 2>&1 | Tee-Object -Variable out | Out-Host
    ($out | Select-String 'stamped real totals into JSON').Line
}

$first = Invoke-Run 'run 1'
if ($Twice) {
    $second = Invoke-Run 'run 2 (same code, same pack)'
    Write-Host "`n=== REPRODUCIBILITY ===" -ForegroundColor Cyan
    Write-Host "run 1: $first"
    Write-Host "run 2: $second"
    if ($first -eq $second) {
        Write-Host 'IDENTICAL — the caches and the deterministic path hold.' -ForegroundColor Green
    } else {
        Write-Host 'DIFFERENT — same code and same pack produced two answers.' -ForegroundColor Red
    }
}

Write-Host "`nMeasure it:" -ForegroundColor Cyan
Write-Host "  $python $(Join-Path $root 'tools\three_numbers.py')"
