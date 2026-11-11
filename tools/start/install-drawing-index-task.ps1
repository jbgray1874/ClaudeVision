<#
    The full listing of the design share, once a week, overnight (SCRUM-199, 10 Nov 2026).

        .\tools\start\install-drawing-index-task.ps1                    Saturdays at 19:00
        .\tools\start\install-drawing-index-task.ps1 -Day Sunday -At 20:00
        .\tools\start\install-drawing-index-task.ps1 -Daily -At 20:00   every night (heavy: see below)
        .\tools\start\install-drawing-index-task.ps1 -Remove

    WHAT IT RUNS. src\drawing_index.py --build --full: every folder under the design customers
    folder and Prototype listed again (230,053 folders, ~10 hours on 9 Nov 2026), then the lookup
    database (index.sqlite) rebuilt from it. While it runs, the hourly design sweep's quick refresh
    stands aside (a lock file), so the two never write the index at once.

    WHY WEEKLY. The hourly quick refresh already checks the top levels and every folder changed in
    the last 90 days, and the pack resolver re-lists a GA's folder live when it is looked up. The
    full listing only catches changes inside dormant folders, which are rare. Every night is
    possible (-Daily) but loads the file server for ~10 hours a night.

    WHY HERE. The share is read with this user's rights, as the sweep and the Live Enquiry runner
    are. The laptop must be on and logged in when it starts; a missed start runs at the next logon.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [string] $Root = "",
    [string] $Day = "Saturday",
    [string] $At = "19:00",
    [switch] $Daily,
    [string] $TaskName = "SDI Drawing Index Full Listing",
    [switch] $Remove
)
$ErrorActionPreference = "Stop"

if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
    if (-not $here) { throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision." }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}
$script = Join-Path $Root "src\drawing_index.py"
if (-not (Test-Path $script)) { throw "$Root has no src\drawing_index.py - sync the engine first, or pass -Root." }

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) { Write-Host "No scheduled task '$TaskName' to remove."; exit 0 }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'. The index and its lookup database are kept." -ForegroundColor Yellow
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $python)) { throw "No engine virtualenv under $Root\.venv" }
$log = Join-Path $Root "output\drawing_index\full_listing.log"

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$script`" --build --full --log `"$log`"" -WorkingDirectory $Root
if ($Daily) {
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    $when = "every night at $At"
} else {
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At
    $when = "every $Day at $At"
}
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 16) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Host "  NOT INSTALLED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  If it says 'denied', open PowerShell as Administrator and run this again." -ForegroundColor Yellow
    exit 8
}
Write-Host "Installed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  runs     $script --build --full ($when; about 10 hours)"
Write-Host "  log      $log"
Write-Host "  next     $((Get-ScheduledTaskInfo -TaskName $TaskName).NextRunTime)"
Write-Host "  run now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  watch:   Get-Content '$log' -Wait -Tail 20"
