<#
    SDI SAMEDAY WATCH: CHECK SAMEDAY EVERY 15 MINUTES, EMAIL WHEN SOMETHING IS WRONG.
    Run FROM THE LAPTOP, VPN connected, after Ship-It (which puts the watch on the server):

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Set-Setting.ps1 SAMEDAY_ALERT_TO you@wearesdi.com    (once)
        .\sdi-intelligence-backend\deploy\Install-SameDay-Watch.ps1

    -Remove takes it away again.

    -- WHY ---------------------------------------------------------------------
    5 November 2026 (James): "this is for sales people and directors who have
    a very high standard ... can we get alerting for this?" A problem should
    reach James before it reaches a director.

    -- WHAT IT DOES --------------------------------------------------------------
    Registers the scheduled task "SDI SameDay Watch" on the server, with the
    same administrator rights Ship-It uses (schtasks over the network). Every
    15 minutes, as SYSTEM, it runs sameday_watch.cmd, which checks SameDay
    (see sameday_watch.py for the list) and emails SAMEDAY_ALERT_TO. Then it
    runs the check once now and shows the result. It changes nothing in
    SameDay, and never reads or prints the keys.
#>
[CmdletBinding()]
param(
    [string]$Server = "10.0.0.5",
    [string]$TaskName = "SDI SameDay Watch",
    [switch]$Remove
)

$ErrorActionPreference = "Continue"
$Backend = "C:\ClaudeVision\sdi-intelligence-backend"            # on the server
$Share = "\\$Server\c$\ClaudeVision\sdi-intelligence-backend"     # the same folder, from this laptop
$Log = "$Share\logs\sameday_watch.log"

# -- Helpers, all defined before anything uses them -------------------------
function Head([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkGray
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkGray
}
function Yes ([string]$Text) { Write-Host "  [ok]    $Text" -ForegroundColor Green }
function Warn([string]$Text) { Write-Host "  [check] $Text" -ForegroundColor Yellow }
function Say ([string]$Text, [string]$Colour = "Gray") { Write-Host "          $Text" -ForegroundColor $Colour }
function Stop-Here([string]$Text) {
    Write-Host ""
    Write-Host "  [STOP]  $Text" -ForegroundColor Red
    Write-Host "          Nothing was changed on the server." -ForegroundColor Red
    Write-Host ""
    exit 1
}
function There([string]$Path) {
    try { return [bool](Test-Path -LiteralPath $Path -ErrorAction Stop) } catch { return $false }
}

Write-Host ""
Write-Host "  SDI SAMEDAY WATCH - CHECKS SAMEDAY EVERY 15 MINUTES" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray

if ($Remove) {
    Head "Taking the watch away"
    & schtasks.exe /Delete /S $Server /TN $TaskName /F | Out-Host
    if ($LASTEXITCODE -eq 0) { Yes "The task '$TaskName' is gone. Nothing will be emailed." }
    else { Warn "schtasks said no (above) - it may not have been there." }
    exit 0
}

# -- 1. Checks: fail closed, before anything changes --------------------------------
Head "1. Checks"
if (-not (There "$Share\sameday_watch.py") -or -not (There "$Share\sameday_watch.cmd")) {
    Stop-Here "The watch is not on the server yet ($Share\sameday_watch.py). Run Ship-It first, VPN on."
}
Yes "The watch is on the server"
if (-not (There "$Share\.venv\Scripts\python.exe")) {
    Stop-Here "SDI Intelligence's Python was not found at $Backend\.venv - the watch uses it."
}
Yes "SDI Intelligence's Python is there"
# Only whether the setting is there - its value is never shown.
$hasTo = $false
try { $hasTo = [bool](Select-String -LiteralPath "$Share\.env" -Pattern '^\s*SAMEDAY_ALERT_TO\s*=\s*\S+@' -Quiet -ErrorAction Stop) } catch { $hasTo = $false }
if (-not $hasTo) {
    Stop-Here "Nobody to email: set it first - .\sdi-intelligence-backend\deploy\Set-Setting.ps1 SAMEDAY_ALERT_TO you@wearesdi.com"
}
Yes "SAMEDAY_ALERT_TO is set"

# -- 2. The task -------------------------------------------------------------------------
Head "2. The scheduled task on $Server"
& schtasks.exe /Create /S $Server /RU SYSTEM /RL HIGHEST /SC MINUTE /MO 15 /TN $TaskName /TR "$Backend\sameday_watch.cmd" /F | Out-Host
if ($LASTEXITCODE -ne 0) {
    Stop-Here "schtasks could not create the task (above). It needs the same administrator rights as Ship-It."
}
Yes "'$TaskName' runs every 15 minutes, as SYSTEM"

# -- 3. Once now ---------------------------------------------------------------------------
Head "3. Checking SameDay once now"
$before = 0
if (There $Log) { $before = (Get-Item -LiteralPath $Log).Length }
& schtasks.exe /Run /S $Server /TN $TaskName | Out-Null
# A "down" result is looked at again a minute later, so this can take up to two minutes.
$deadline = (Get-Date).AddSeconds(150)
$done = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    if ((There $Log) -and (Get-Item -LiteralPath $Log).Length -gt $before) {
        Start-Sleep -Seconds 3
        $done = $true
        break
    }
}
if ($done) {
    Say "What it found (the end of logs\sameday_watch.log on the server):" White
    Get-Content -LiteralPath $Log -Tail 6 | ForEach-Object { Say $_ }
} else {
    Warn "No result yet. It runs every 15 minutes regardless; its log is $Log"
}

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host "  The watch is on. A problem is emailed once, again every 3 hours while it" -ForegroundColor Green
Write-Host "  lasts, and 'all clear' when it is fixed - between 7am and 7pm" -ForegroundColor Green
Write-Host "  (SAMEDAY_ALERT_HOURS). 'OK' in the line above means nothing is wrong now." -ForegroundColor Green
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
