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
    [string] $Root = (Resolve-Path "$PSScriptRoot\..\.."),
    [switch] $Force
)

$ErrorActionPreference = "Stop"
$python = Join-Path $Root "sdi-intelligence-backend\.venv\Scripts\python.exe"
$app    = Join-Path $Root "sdi-intelligence-backend\app.py"

if (-not (Test-Path $python)) { throw "No service virtualenv at $python" }
if (-not (Test-Path $app))    { throw "No app.py at $app" }

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
Write-Host "SDI Intelligence service" -ForegroundColor Cyan
Write-Host "    http://localhost:$Port/estimating" -ForegroundColor Cyan
Write-Host "Ctrl+C to stop."
Write-Host ""
& $python $app
