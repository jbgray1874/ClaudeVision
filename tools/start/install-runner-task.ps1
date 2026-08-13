<#
    Install the SDI estimating runner as a Scheduled Task that starts itself and
    restarts itself.

        .\tools\start\install-runner-task.ps1
        .\tools\start\install-runner-task.ps1 -Remove

    WHY A SCHEDULED TASK AND NOT A WINDOWS SERVICE.

    This is the important part and it is easy to get wrong in a way that looks
    right for a week. The runner drives SOLIDWORKS and Excel through COM, and COM
    needs a licensed, INTERACTIVE desktop session. A normal Windows service runs
    in session 0 with no desktop, so it would install cleanly, start cleanly,
    report itself healthy, and then fail on every estimate the moment it tried to
    open SOLIDWORKS. NSSM would do the same thing. "Allow service to interact
    with desktop" has not worked properly since Windows Vista and does not work
    here.

    A Scheduled Task set to "run only when the user is logged on" runs in that
    user's real desktop session, which is the same place a hand-started runner
    runs. It survives the window being closed, starts at logon, and Windows
    restarts it if the process exits.

    WHAT THIS FIXES AND WHAT IT DOES NOT. It stops a closed window, a stray
    Ctrl+C or a crash from leaving the page saying "no runner connected" until
    somebody notices. It does NOT stop the machine being logged out, locked by a
    policy, or shut down - nothing can, because without a desktop session there
    is no SOLIDWORKS.

    The runner already refuses to start twice (an OS lock, released however the
    process dies), so the task and a hand-started window cannot fight: whichever
    is second says so and exits.

    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [string] $Root     = (Resolve-Path "$PSScriptRoot\..\.."),
    [string] $Server   = ("http://localhost:" + $(if ($env:SDI_PORT) { $env:SDI_PORT } else { "8071" })),
    [string] $TaskName = "SDI Estimating Runner",
    [switch] $Remove
)

$ErrorActionPreference = "Stop"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName'." -ForegroundColor Yellow
    Write-Host "The runner is no longer started automatically. Any runner running right"
    Write-Host "now keeps running until it stops."
    exit 0
}

$python = Join-Path $Root ".venv\Scripts\pythonw.exe"    # windowless; falls back below
if (-not (Test-Path $python)) { $python = Join-Path $Root ".venv\Scripts\python.exe" }
$runner = Join-Path $Root "tools\runner\sdi_estimate_runner.py"

if (-not (Test-Path $python)) { throw "No engine virtualenv at $python" }
if (-not (Test-Path $runner)) { throw "No runner at $runner" }

# RUN AS THE LOGGED-ON USER, IN THEIR SESSION. -LogonType Interactive is the
# whole point: it is what gives the process a desktop, and therefore SOLIDWORKS.
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "`"$runner`" --server `"$Server`"" -WorkingDirectory $Root

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# RestartInterval/RestartCount are what make this worth doing: if the process
# exits for any reason, Windows starts it again a minute later, up to three times
# an hour, without anybody watching. ExecutionTimeLimit 0 because an estimate can
# legitimately take an hour and a task that kills its own work is worse than no
# task at all.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName'." -ForegroundColor Green
Write-Host "  python   $python"
Write-Host "  server   $Server"
Write-Host "  restarts every minute if it exits, three times an hour"
Write-Host "  starts   at logon for $env:USERNAME, in that session (SOLIDWORKS needs one)"
Write-Host ""
Write-Host "Start it now without logging out:" -ForegroundColor Cyan
Write-Host "    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "It writes everything it says to:" -ForegroundColor Cyan
Write-Host "    $Root\output\logs\runner-<date>.log"
Write-Host "so a death leaves a record rather than a closed window."
Write-Host ""
Write-Host "Stop it:      Stop-ScheduledTask  -TaskName '$TaskName'"
Write-Host "Remove it:    .\tools\start\install-runner-task.ps1 -Remove"
