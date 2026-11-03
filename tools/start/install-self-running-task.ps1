<#
    Install the watcher behind the portal's "AI Estimate Self-Running" button (D-588).

        .\tools\start\install-self-running-task.ps1
        .\tools\start\install-self-running-task.ps1 -Server http://localhost:8071
        .\tools\start\install-self-running-task.ps1 -Remove

    WHAT IT RUNS. src\self_running.py: ask the portal every minute whether self-running is
    switched on; while it is, read the AI Live Enquiry workbook from the top, take each row
    with AI CHECK = YES, a QTY and AICompleted NO, N or Re-Run, find its drawings under the
    Live Enquiry folder (customer, then the folder carrying the drawing number), and run every
    ready job through the portal one after another (D-608). Switched off, it runs nothing. Its output goes to
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
    # BOTH SERVICES ON THIS MACHINE, LIKE THE RUNNER (D-644): the watcher reports to every
    # one on the list, so the switch works from whichever the page or the phone reached.
    # Add another (e.g. SDI-APP01's 8071) with -Server "http://localhost:8072,http://...".
    [string] $Server   = $(if ($env:SDI_SERVER) { $env:SDI_SERVER } else { "http://localhost:8072,http://localhost:8071" }),
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

# WHICH WORKBOOK THE TASK WILL READ (D-608b). A task reads C:\ClaudeVision\.env, never this
# window. SDI_LIVE_ENQUIRY_WORKBOOK there wins; without it, AI-Live-Enquiry.xlsx in the Live
# Enquiry folder is read, by its UNC path: a task has no K: drive.
$envFile = Join-Path $Root ".env"
$book = "\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\AI-Live-Enquiry.xlsx"
$fromEnv = $null
if (Test-Path $envFile) {
    $fromEnv = Select-String -Path $envFile -Pattern '^\s*SDI_LIVE_ENQUIRY_WORKBOOK\s*=\s*(.+?)\s*$' |
        Select-Object -First 1
}
if ($fromEnv) {
    $book = $fromEnv.Matches[0].Groups[1].Value.Trim('"')
    Write-Host "  workbook $book  (SDI_LIVE_ENQUIRY_WORKBOOK in .env)"
} else {
    Write-Host "  workbook $book  (the default; nothing set in .env)"
}
if (-not (Test-Path $book)) {
    Write-Host "That workbook is not there: $book" -ForegroundColor Red
    Write-Host "Put the AI Live Enquiry sheet there, or set SDI_LIVE_ENQUIRY_WORKBOOK in $envFile, and run this again." -ForegroundColor Red
    exit 2
}

# ONE SHEET, ONE WATCHER. The old always-on task holds the same lock.
$old = Get-ScheduledTask -TaskName $OldTask -ErrorAction SilentlyContinue
if ($old) {
    Stop-ScheduledTask -TaskName $OldTask -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $OldTask -Confirm:$false
    Write-Host "Removed '$OldTask': self-running replaces it (one sheet, one lock). A job it had queued carries on in the portal." -ForegroundColor Yellow
}

# A WATCHER ALREADY RUNNING KEEPS ITS OLD SETTINGS (D-648). Registering with -Force changes
# the task's definition, not the process it started; and with MultipleInstances IgnoreNew the
# Start below does nothing while that process lives. On 3 Nov 2026 the watcher went on
# reporting to the laptop's services only, after this was re-run with SDI-App01 added, and the
# phone said "no self-running watcher is connected". So the running watcher is stopped first,
# and the lock it can no longer release is cleared if its process is gone.
$current = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($current) { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue }
$watchers = @(Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*self_running.py*" })
foreach ($w in $watchers) { Stop-Process -Id $w.ProcessId -Force -ErrorAction SilentlyContinue }
if ($watchers.Count) {
    Write-Host "  stopped the running watcher (pid $(($watchers | ForEach-Object { $_.ProcessId }) -join ', ')) so the new settings take effect" -ForegroundColor Yellow
    Start-Sleep -Seconds 2
}
$ledger = Join-Path $Root "output\live_enquiry\ledger.json"
if (Test-Path $envFile) {
    $ledgerEnv = Select-String -Path $envFile -Pattern '^\s*SDI_LIVE_ENQUIRY_LEDGER\s*=\s*(.+?)\s*$' |
        Select-Object -First 1
    if ($ledgerEnv) { $ledger = $ledgerEnv.Matches[0].Groups[1].Value.Trim('"') }
}
$lock = Join-Path (Split-Path -Parent $ledger) "live_enquiry.lock"
if (Test-Path $lock) {
    $holder = ((Get-Content -LiteralPath $lock -ErrorAction SilentlyContinue) -split "\s+")[0]
    if (-not ($holder -as [int]) -or -not (Get-Process -Id ([int]$holder) -ErrorAction SilentlyContinue)) {
        Remove-Item -LiteralPath $lock -Force -ErrorAction SilentlyContinue
        Write-Host "  cleared the lock left by a watcher that is no longer running" -ForegroundColor Yellow
    }
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
Start-Sleep -Seconds 12
Write-Host ""
Write-Host "  task state: $((Get-ScheduledTask -TaskName $TaskName).State)" -ForegroundColor Green
# WHAT THE NEW WATCHER SAYS (D-648): the services it reports to, and any it cannot reach.
if (Test-Path $log) {
    Get-Content -LiteralPath $log -Tail 40 |
        Where-Object { $_ -match "reporting to|did not answer|holds .*lock|Another Live Enquiry" } |
        Select-Object -Last 4 | ForEach-Object { Write-Host "  $_" -ForegroundColor Cyan }
}
Write-Host "  watch it:   Get-Content '$log' -Wait -Tail 30"
