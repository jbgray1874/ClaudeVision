<#
    Sweep the design share for new drawing packs every hour, for as long as this laptop is up.

        .\tools\start\install-design-sweep-task.ps1
        .\tools\start\install-design-sweep-task.ps1 -Server http://localhost:8071
        .\tools\start\install-design-sweep-task.ps1 -Remove

    WHAT IT RUNS. src\design_sweep.py: every SDI_DESIGN_SWEEP_MINUTES (60) it walks the client
    folders under SDI_DESIGN_SWEEP_ROOT (W:\ unless set), finds the drawing-pack folders and
    reports the new or changed ones to the portal, which shows them on the control panel under
    NEW DRAWING PACKS. The first sweep records what is already there and flags nothing.

    WHY HERE, NOT ON THE SERVICE. The share is reached with this user's rights; the service host
    has none. A Scheduled Task in the user's session, like the Live Enquiry runner: it starts at
    logon, Windows restarts it if it exits, a check every five minutes brings it back.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [string] $Root = "",
    [string] $Server   = $(if ($env:SDI_SERVER) { $env:SDI_SERVER } else { "http://localhost:8072" }),
    [string] $TaskName = "SDI Design Share Sweep",
    [switch] $Remove
)
$ErrorActionPreference = "Stop"

if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    if (-not $here) { throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision." }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}
$script = Join-Path $Root "src\design_sweep.py"
if (-not (Test-Path $script)) { throw "$Root has no src\design_sweep.py - sync the engine first, or pass -Root." }

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) { Write-Host "No scheduled task '$TaskName' to remove."; exit 0 }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'. The ledger of packs seen is kept (output\design_sweep\ledger.json)." -ForegroundColor Yellow
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $python)) { throw "No engine virtualenv under $Root\.venv" }
$log = Join-Path $Root "output\design_sweep\sweep.log"

$envFile = Join-Path $Root ".env"
$hasRoot = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*SDI_DESIGN_SWEEP_ROOT\s*=' -Quiet)
if (-not $hasRoot) {
    Write-Host "SDI_DESIGN_SWEEP_ROOT is not in $envFile, so the sweep reads W:\ ." -ForegroundColor Yellow
    Write-Host "If the client folders sit lower down, add for example:  SDI_DESIGN_SWEEP_ROOT=W:\Clients" -ForegroundColor Yellow
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$script`" --server `"$Server`" --log `"$log`"" -WorkingDirectory $Root
$triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
try {
    $check = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) -RepetitionInterval (New-TimeSpan -Minutes 5)
    $check.Repetition.Duration = ""
    $triggers += $check
} catch {
    Write-Host "  note: no 5-minute check ($($_.Exception.Message)); logon and restart-on-exit only." -ForegroundColor Yellow
}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Host "  NOT INSTALLED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  If it says 'denied', open PowerShell as Administrator and run this again." -ForegroundColor Yellow
    exit 8
}
Write-Host "Installed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  runs     $script (every SDI_DESIGN_SWEEP_MINUTES, 60 unless set)"
Write-Host "  portal   $Server"
Write-Host "  log      $log"
Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Write-Host "  task state: $((Get-ScheduledTask -TaskName $TaskName).State)" -ForegroundColor Green
Write-Host "  watch it:   Get-Content '$log' -Wait -Tail 30"
