<#
.SYNOPSIS
    Why did the presence sync not do anything? Answer in one command.

.DESCRIPTION
    "The job won't run" has several distinct causes that look identical in Task
    Scheduler. This reports each of them: whether the task exists, when it last
    ran and with what result, whether a repetition interval actually stuck,
    what the last run printed, and how fresh the snapshot and status file are.

    Read-only. Safe to run at any time, elevated or not.

.EXAMPLE
    .\check_presence_task.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "BrightHR-InVentry Presence Sync",
    [string]$LogFile = "C:\SDIIntelligence\hr\snapshots\presence_sync.log",
    [string]$SnapshotDir = "C:\SDIIntelligence\hr\snapshots",
    [int]$Tail = 40
)

function Head($t) { Write-Host "`n== $t" -ForegroundColor Cyan }

# Task Scheduler's own result codes, which are not error codes in the usual
# sense - 0x41301 in particular means "running", not "broken".
$codes = @{
    0          = "ok"
    1          = "aborted by the script - a guard tripped or a system was unreachable"
    2          = "ran, but something was suppressed or partially failed"
    267009     = "currently running (0x41301)"
    267011     = "has never run (0x41303)"
    267014     = "last run was terminated by the user (0x41306)"
    2147942401 = "the program could not be found (0x80070002-ish) - check the interpreter path"
    2147943712 = "logon failure / the account cannot run this task (0x8007052E)"
    2147750687 = "an instance was already running and IgnoreNew skipped this one (0x800710E0)"
}

Head "Task"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "   No task named '$TaskName'. Run deploy\install_presence_task.ps1." -ForegroundColor Red
    return
}
Write-Host "   State    : $($task.State)"
Write-Host "   Runs as  : $($task.Principal.UserId) ($($task.Principal.LogonType), $($task.Principal.RunLevel))"
Write-Host "   Command  : $($task.Actions[0].Execute) $($task.Actions[0].Arguments)"
Write-Host "   Workdir  : $($task.Actions[0].WorkingDirectory)"
if ($task.State -eq "Disabled") {
    Write-Host "   Disabled - nothing will fire. Enable-ScheduledTask -TaskName '$TaskName'" -ForegroundColor Red
}

Head "Schedule"
$rep = $task.Triggers[0].Repetition
if ($rep.Interval) {
    Write-Host "   Every $($rep.Interval), for $(if ($rep.Duration) { $rep.Duration } else { 'an indefinite period' })" -ForegroundColor Green
} else {
    Write-Host "   No repetition interval - this task fires once and never again." -ForegroundColor Red
    Write-Host "   Re-run install_presence_task.ps1; it now sets a repetition duration." -ForegroundColor Red
}

Head "Last run"
$info = Get-ScheduledTaskInfo -TaskName $TaskName
$code = [int64]$info.LastTaskResult
$meaning = if ($codes.ContainsKey($code)) { $codes[$code] } else { "unmapped code" }
Write-Host "   Last run : $($info.LastRunTime)"
Write-Host "   Result   : $code  ($meaning)  [0x$('{0:X}' -f $code)]"
Write-Host "   Next run : $($info.NextRunTime)"
Write-Host "   Missed   : $($info.NumberOfMissedRuns)"

Head "Run log (last $Tail lines of $LogFile)"
if (Test-Path $LogFile) {
    Get-Content $LogFile -Tail $Tail
} else {
    Write-Host "   Not written yet. Either the task has not run, or it failed before" -ForegroundColor Yellow
    Write-Host "   PowerShell started - which points at the interpreter path, the" -ForegroundColor Yellow
    Write-Host "   execution policy, or the account." -ForegroundColor Yellow
}

Head "Output freshness"
foreach ($name in @("hr_status.json", "hr_pipeline.log")) {
    $p = Join-Path $SnapshotDir $name
    if (Test-Path $p) {
        $age = [int]((Get-Date) - (Get-Item $p).LastWriteTime).TotalMinutes
        $colour = if ($age -le 15) { "Green" } else { "Yellow" }
        Write-Host "   $name  $age minute(s) old" -ForegroundColor $colour
    } else {
        Write-Host "   $name  missing" -ForegroundColor Yellow
    }
}
Write-Host ""
Write-Host "A snapshot older than BLIP_MAX_STALE_MINUTES (15) is refused by the push" -ForegroundColor DarkGray
Write-Host "on purpose - a stale fire roll is worse than one that has not moved." -ForegroundColor DarkGray
