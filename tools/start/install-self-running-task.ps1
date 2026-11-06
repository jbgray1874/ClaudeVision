<#
    Install the watcher behind the portal's "AI Estimate Self-Running" button (D-588).

        .\tools\start\install-self-running-task.ps1
        .\tools\start\install-self-running-task.ps1 -Server http://localhost:8071
        .\tools\start\install-self-running-task.ps1 -Remove

    WHAT IT RUNS. src\self_running.py: ask the portal every minute whether self-running is
    switched on; while it is, read the Live Enquiry workbook, collect each waiting row's
    drawings from Production into the Live Enquiry folder, and run every ready job through
    the portal one after another. Switched off, it runs nothing. Its output goes to
    output\live_enquiry\self_running.log; every read rewrites
    output\live_enquiry\live_enquiry_status.csv.

    IT REPLACES THE ALWAYS-ON LIVE ENQUIRY TASK. Both drive one sheet through one ledger and
    share one lock, so only one can run; the button exists so that a person decides when the
    sheet is worked. If 'SDI Live Enquiry Runner' is installed it is removed here, and this
    says so. A job that task had queued carries on in the portal.

    WHAT ELSE MUST BE UP. This only QUEUES. The estimates are done by the estimating runner
    (install-runner-task.ps1) through the portal service; with either down, the page shows
    the watcher's report and a cycle says why nothing ran.

    AS LONG AS THE LAPTOP IS: logged on, awake and on the network - the same terms as the
    estimating runner, for the same reason (the share is reached with this user's rights).

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [string] $Root = "",
    [string] $Server   = $(if ($env:SDI_SERVER) { $env:SDI_SERVER } else { "http://localhost:8072" }),
    [string] $TaskName = "SDI AI Estimate Self-Running",
    [string] $OldTask  = "SDI Live Enquiry Runner",
    [switch] $Remove
)

$ErrorActionPreference = "Stop"

if (-not $Root) {
    $here = $PSScriptRoot
    if (-not $here -and $MyInvocation.MyCommand.Path) {
        $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    if (-not $here) { throw "Cannot work out where this script is. Pass -Root C:\ClaudeVision." }
    $Root = (Resolve-Path (Join-Path $here "..\..")).Path
}
$script = Join-Path $Root "src\self_running.py"
if (-not (Test-Path $script)) { throw "$Root has no src\self_running.py - pass -Root, or pull first." }

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) { Write-Host "No scheduled task '$TaskName' to remove."; exit 0 }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'. A queued estimate carries on in the portal." -ForegroundColor Yellow
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $python)) { throw "No engine virtualenv under $Root\.venv" }
$log = Join-Path $Root "output\live_enquiry\self_running.log"

# THE WORKBOOK MUST BE IN .env, NOT ONLY IN THIS WINDOW. A task reads C:\ClaudeVision\.env.
$envFile = Join-Path $Root ".env"
$hasBook = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*SDI_LIVE_ENQUIRY_WORKBOOK\s*=' -Quiet)
if (-not $hasBook) {
    Write-Host "SDI_LIVE_ENQUIRY_WORKBOOK is not in $envFile." -ForegroundColor Red
    Write-Host "Add it (no quotes round a UNC path) and run this again:" -ForegroundColor Red
    Write-Host '  SDI_LIVE_ENQUIRY_WORKBOOK=\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries\Live Enquiry (no password).xlsx'
    exit 2
}

# ONE SHEET, ONE WATCHER. The old always-on task holds the same lock.
$old = Get-ScheduledTask -TaskName $OldTask -ErrorAction SilentlyContinue
if ($old) {
    Stop-ScheduledTask -TaskName $OldTask -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $OldTask -Confirm:$false
    Write-Host "Removed '$OldTask': self-running replaces it (one sheet, one lock). A job it had queued carries on in the portal." -ForegroundColor Yellow
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$script`" --server `"$Server`" --log `"$log`"" -WorkingDirectory $Root

$triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
try {
    $sweep = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 5)
    $sweep.Repetition.Duration = ""
    $triggers += $sweep
} catch {
    Write-Host "  note: no 5-minute sweep ($($_.Exception.Message)); logon and restart-on-exit only." -ForegroundColor Yellow
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

try {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
        -Settings $settings -Principal $principal -Force -ErrorAction Stop | Out-Null
} catch {
    Write-Host "  NOT INSTALLED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  If it says 'denied', open PowerShell as Administrator and run this again." -ForegroundColor Yellow
    exit 8
}

Write-Host "Installed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  runs     $script"
Write-Host "  portal   $Server  (the button on its estimating page switches it on and off)"
Write-Host "  log      $log"
Write-Host "  status   $(Join-Path $Root 'output\live_enquiry\live_enquiry_status.csv')"
Write-Host "  starts   at logon for $env:USERNAME; restarts if it exits; checked every 5 minutes"

Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Write-Host ""
Write-Host "  task state: $((Get-ScheduledTask -TaskName $TaskName).State)" -ForegroundColor Green
Write-Host "  watch it:   Get-Content '$log' -Wait -Tail 30"
