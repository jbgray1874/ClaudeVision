<#
    Keep the Live Enquiry runner watching the workbook for as long as this laptop is up.

        .\tools\start\install-live-enquiry-task.ps1
        .\tools\start\install-live-enquiry-task.ps1 -Server http://localhost:8071
        .\tools\start\install-live-enquiry-task.ps1 -Remove

    WHAT IT RUNS. src\live_enquiry_runner.py watch: read the Live Enquiry workbook every
    SDI_LIVE_ENQUIRY_POLL_MINUTES (15), queue each ready row through the portal one after
    another, wait for each to finish. Its output goes to output\live_enquiry\watch.log,
    and every scan rewrites output\live_enquiry\live_enquiry_status.csv.

    WHAT ELSE MUST BE UP. This only QUEUES. The estimates are done by the estimating
    runner (install-runner-task.ps1) through the portal service (install-service-task.ps1);
    with either down, a cycle says "no runner connected" in the log and tries again on
    the next one. Install all three.

    24 x 7, AS LONG AS THE LAPTOP IS: logged on, awake and on the network. A Scheduled
    Task in the user's session, like the estimating runner, because the runner it feeds
    needs that session for SOLIDWORKS and Excel and the share is reached with this user's
    rights. It starts at logon, Windows restarts it if it exits, and a sweep every five
    minutes brings it back if Windows has given up. It refuses to run twice (its own lock).

    SLEEP STOPS EVERYTHING. A sleeping laptop runs no task. While on mains power:
        powercfg /change standby-timeout-ac 0
        powercfg /change hibernate-timeout-ac 0
    This script does not change power settings; it says whether they will interrupt it.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [string] $Root = "",
    # The portal this laptop serves. SDI_SERVER if the window knows it; else this machine's
    # hand-started service on 8072 (restart-service.ps1's default here).
    [string] $Server   = $(if ($env:SDI_SERVER) { $env:SDI_SERVER } else { "http://localhost:8072" }),
    [string] $TaskName = "SDI Live Enquiry Runner",
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
$script = Join-Path $Root "src\live_enquiry_runner.py"
if (-not (Test-Path $script)) { throw "$Root has no src\live_enquiry_runner.py - pass -Root." }

if ($Remove) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) { Write-Host "No scheduled task '$TaskName' to remove."; exit 0 }
    # Stopping the watcher never loses an estimate: the run it queued belongs to the portal
    # and finishes there. The next start finds it in the ledger and asks the portal about it.
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed '$TaskName'. A queued estimate carries on in the portal." -ForegroundColor Yellow
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { $python = Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $python)) { throw "No engine virtualenv under $Root\.venv" }
$log = Join-Path $Root "output\live_enquiry\watch.log"

# THE WORKBOOK MUST BE IN .env, NOT ONLY IN THIS WINDOW. A task does not inherit a variable
# set with $env: here; it reads C:\ClaudeVision\.env like every other entry point.
$envFile = Join-Path $Root ".env"
$hasBook = (Test-Path $envFile) -and (Select-String -Path $envFile -Pattern '^\s*SDI_LIVE_ENQUIRY_WORKBOOK\s*=' -Quiet)
if (-not $hasBook) {
    Write-Host "SDI_LIVE_ENQUIRY_WORKBOOK is not in $envFile." -ForegroundColor Red
    Write-Host "Add it (no quotes round a UNC path) and run this again:" -ForegroundColor Red
    Write-Host '  SDI_LIVE_ENQUIRY_WORKBOOK=\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Live Enquiries\Live Enquiry (no password).xlsx'
    exit 2
}

$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$script`" watch --server `"$Server`" --log `"$log`"" -WorkingDirectory $Root

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
Write-Host "  runs     $script watch"
Write-Host "  portal   $Server"
Write-Host "  log      $log"
Write-Host "  status   $(Join-Path $Root 'output\live_enquiry\live_enquiry_status.csv')"
Write-Host "  starts   at logon for $env:USERNAME; restarts if it exits; checked every 5 minutes"

# SAY WHETHER SLEEP WILL STOP IT. 0 = never.
try {
    $ac = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE | Select-String "Current AC Power Setting Index") -replace '.*:\s*0x', ''
    if ($ac -and [Convert]::ToInt32($ac, 16) -gt 0) {
        Write-Host ""
        Write-Host "  THIS LAPTOP SLEEPS after $([Convert]::ToInt32($ac, 16) / 60) min on mains power, and a sleeping laptop runs nothing." -ForegroundColor Yellow
        Write-Host "  To keep it awake on mains:  powercfg /change standby-timeout-ac 0" -ForegroundColor Yellow
    }
} catch { }

Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Write-Host ""
Write-Host "  task state: $((Get-ScheduledTask -TaskName $TaskName).State)" -ForegroundColor Green
Write-Host "  watch it:   Get-Content '$log' -Wait -Tail 30"
