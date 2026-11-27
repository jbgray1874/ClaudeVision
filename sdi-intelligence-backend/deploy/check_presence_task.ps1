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
#
# Keys are STRINGS on purpose. PowerShell parses small literals (0, 1, 267009)
# as Int32 and large ones (2147942402) as Int64, while LastTaskResult is looked
# up as Int64 - and in .NET an Int64 0 is not equal to an Int32 0. Numeric keys
# therefore silently miss exactly the codes you see most: ok, aborted, partial,
# running. Comparing as text has no such trap.
$codes = @{
    "0"          = "ok"
    "1"          = "aborted by the script - a guard tripped or a system was unreachable"
    "2"          = "ran, but something was suppressed or partially failed"
    "267009"     = "currently running (0x41301)"
    "267011"     = "has never run (0x41303)"
    "267014"     = "last run was terminated by the user (0x41306)"
    "2147942402" = "the program could not be found (0x80070002) - check the interpreter path"
    "2147943726" = "logon failure - the account cannot run this task (0x8007052E)"
    "2147750687" = "an instance was already running, so this one was skipped (0x8004131F)"
}

Head "Task"
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "   No task named '$TaskName' exists." -ForegroundColor Red

    # "No task" is not one fault, it is several, and they need different fixes.
    # Check the ones that can be checked from here rather than leaving the
    # reader to guess.
    $near = Get-ScheduledTask -ErrorAction SilentlyContinue |
            Where-Object { $_.TaskName -match "BrightHR|InVentry|Presence|Blip" }
    if ($near) {
        Write-Host "   But these look related - the task may be registered under another name:" -ForegroundColor Yellow
        $near | ForEach-Object { Write-Host "     $($_.TaskPath)$($_.TaskName)  [$($_.State)]" }
        Write-Host "   Re-run with -TaskName '<that name>' to inspect it." -ForegroundColor Yellow
    }

    $elevated = ([Security.Principal.WindowsPrincipal] `
        [Security.Principal.WindowsIdentity]::GetCurrent()
        ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

    Write-Host ""
    Write-Host "   Why the installer may not have got as far as registering:" -ForegroundColor Cyan
    if (-not $elevated) {
        Write-Host "     * This session is NOT elevated. Registering a task that runs as" -ForegroundColor Red
        Write-Host "       SYSTEM needs Administrator. Open PowerShell as Administrator." -ForegroundColor Red
    } else {
        Write-Host "     * This session is elevated, so permissions are not the problem." -ForegroundColor Green
    }

    $backend = (Resolve-Path "$PSScriptRoot\..").Path
    if (Test-Path (Join-Path $backend ".env")) {
        Write-Host "     * .env found in $backend" -ForegroundColor Green
    } else {
        Write-Host "     * No .env in $backend - the installer throws here, by design," -ForegroundColor Red
        Write-Host "       because the task would abort on every cycle without it." -ForegroundColor Red
        Write-Host "       .env is deliberately not in git. Check the other worktree" -ForegroundColor Red
        Write-Host "       (git worktree list) and copy it across." -ForegroundColor Red
    }

    $repoRoot = Split-Path $backend -Parent
    $py = @(
        (Join-Path $backend  ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot "venv\Scripts\python.exe")
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($py) {
        Write-Host "     * Interpreter found: $py" -ForegroundColor Green
    } else {
        $onPath = Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($onPath) {
            Write-Host "     * No venv in this checkout; PATH has $($onPath.Source)" -ForegroundColor Yellow
            Write-Host "       The installer will use it but SYSTEM may not be able to." -ForegroundColor Yellow
        } else {
            Write-Host "     * No Python found in this checkout or on PATH - the installer" -ForegroundColor Red
            Write-Host "       throws here. Pass -Python <path to python.exe>." -ForegroundColor Red
        }
    }

    Write-Host ""
    Write-Host "   Then, in an ELEVATED prompt:" -ForegroundColor Cyan
    Write-Host "     .\deploy\install_presence_task.ps1"
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
$meaning = if ($codes.ContainsKey("$code")) { $codes["$code"] } else { "unmapped code" }
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
