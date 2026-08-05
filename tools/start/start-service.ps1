<#
    Start the SDI Intelligence service.

        .\tools\start\start-service.ps1              # port 8072
        .\tools\start\start-service.ps1 -Port 8071   # somewhere else

    WHY THIS EXISTS. The port is read from $env:SDI_PORT, and a PowerShell
    environment variable belongs to ONE WINDOW. Set it, open a second window for
    the runner, come back tomorrow — and app.py silently falls back to its
    default and collides with whatever already holds it. The error names the
    port and nothing else, so the fix looks like "something is broken" rather
    than "this window never knew which port you meant".
#>
[CmdletBinding()]
param(
    [int]    $Port = 8072,
    [string] $Root = (Resolve-Path "$PSScriptRoot\..\.."),
    [switch] $Force          # stop whatever is on the port first
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Root "sdi-intelligence-backend\.venv\Scripts\python.exe"
$app    = Join-Path $Root "sdi-intelligence-backend\app.py"

if (-not (Test-Path $python)) { throw "No service virtualenv at $python" }
if (-not (Test-Path $app))    { throw "No app.py at $app" }

# SAY WHO HAS IT, not just that somebody does. "Only one usage of each socket
# address" sends you to the firewall; "held by python.exe (pid 60096), started
# 14:02, running as SDI\james.gray" sends you to the right window.
$held = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($held) {
    $owners = $held.OwningProcess | Select-Object -Unique | ForEach-Object {
        $p  = Get-Process -Id $_ -ErrorAction SilentlyContinue
        $ci = Get-CimInstance Win32_Process -Filter "ProcessId=$_" -ErrorAction SilentlyContinue
        $ow = if ($ci) { Invoke-CimMethod -InputObject $ci -MethodName GetOwner -ErrorAction SilentlyContinue }
        [pscustomobject]@{ PID = $_; Name = $p.ProcessName; Started = $p.StartTime
                           RunAs = if ($ow) { "$($ow.Domain)\$($ow.User)" } else { "?" } }
    }
    if ($Force) {
        Write-Host "Port $Port is in use — stopping:" -ForegroundColor Yellow
        $owners | Format-Table -AutoSize | Out-String | Write-Host
        $owners.PID | ForEach-Object { Stop-Process -Id $_ -Force }
        Start-Sleep -Milliseconds 700
    } else {
        Write-Host "Port $Port is already in use by:" -ForegroundColor Red
        $owners | Format-Table -AutoSize | Out-String | Write-Host
        Write-Host "Re-run with -Force to stop it, or -Port <n> to use another." -ForegroundColor Yellow
        exit 1
    }
}

$env:SDI_PORT = "$Port"          # set HERE, so this window cannot disagree with itself
Write-Host "SDI Intelligence service  ·  http://localhost:$Port/estimating" -ForegroundColor Cyan
Write-Host "Ctrl+C to stop.`n"
& $python $app
