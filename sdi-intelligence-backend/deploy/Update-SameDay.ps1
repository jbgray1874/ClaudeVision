<#
    UPDATE SDI SAMEDAY ON THE SERVER FROM ITS PRIVATE REPOSITORY.

    Run ON THE SERVER (10.0.0.5), over Remote Desktop, in PowerShell (not
    the ISE) opened with "Run as administrator".
    First copy this one file across, FROM THE LAPTOP:

        Copy-Item C:\ClaudeVision\sdi-intelligence-backend\deploy\Update-SameDay.ps1 \\10.0.0.5\c$\Tools\

    then, on the server:

        powershell -ExecutionPolicy Bypass -File C:\Tools\Update-SameDay.ps1

    To try a branch before it is merged, name it:

        powershell -ExecutionPolicy Bypass -File C:\Tools\Update-SameDay.ps1 -Branch claude/inspiring-planck-8juriz

    The first time, a GitHub sign-in window opens: sign in as jbgray1874, the
    account the private repository belongs to.

    -- WHY THIS EXISTS -------------------------------------------------------
    4 November 2026: SameDay's code now lives in github.com/jbgray1874/sdi-sameday
    (private), where the "any order" and noisy-room changes were made. Muhammad's
    UPDATE_SAME_DAY.bat copies K: instead, so on this server it would put the
    older code back - and it starts a second copy of SameDay outside its
    service, which then fights the service for port 5020. Use this here.

    -- WHAT IT CHANGES ---------------------------------------------------------
    The code in C:\SDI_Automation, from the repository, and then it restarts
    the SDISameDay and SDICraft services. The code it replaces is kept first in
    C:\SDI_Automation\backups\, and the end of the run says how to put it back.

    -- WHAT IT NEVER TOUCHES ---------------------------------------------------
    The keys (.env), the chats (lite.db), Craft's log, renders and uploads
    (out\, client_files\), the spend log (studio_data\), logs, the Python
    packages (.venv-gpu), K:, and every other service - SDIIntelligence
    included. The repository holds no data, so there is none to copy over.
#>
[CmdletBinding()]
param(
    [string]$Branch = "main",
    [string]$Repo = "https://jbgray1874@github.com/jbgray1874/sdi-sameday.git",
    # The server's own copy of the repository, used for nothing else.
    [string]$Code = "C:\Tools\sdi-sameday",
    [string]$Target = "C:\SDI_Automation"
)

$ErrorActionPreference = "Continue"
$Services = @("SDISameDay", "SDICraft")
$Status = "http://localhost:5020/api/status"

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
    Write-Host "          SameDay was not changed: it is still running the code it had." -ForegroundColor Red
    Write-Host ""
    exit 1
}
# NOT called "Git": PowerShell names are case-blind and a function beats a
# program, so a function called Git would call itself instead of git.exe.
function RunGit([string[]]$Arguments) {
    & git.exe -C $Code @Arguments | Out-Host
    return $LASTEXITCODE
}
# A log tail fit to be pasted into chat: anything key-shaped is removed first.
function SafeTail([string]$Path, [int]$Lines = 20) {
    if (-not (Test-Path -LiteralPath $Path)) { Say "(no log yet at $Path)"; return }
    foreach ($line in (Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue)) {
        Say ($line -replace 'sk-[A-Za-z0-9_\-]{16,}|xai-[A-Za-z0-9]{16,}', '[key removed]')
    }
}
function RunningVersion {
    try { return [string](Invoke-RestMethod -Uri $Status -TimeoutSec 5).version } catch { return "" }
}

Write-Host ""
Write-Host "  SDI SAMEDAY - UPDATE FROM ITS REPOSITORY ($Branch)" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray

# -- 1. Checks: the right machine, and SameDay installed ---------------------------
Head "1. Checks before anything is changed"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Stop-Here "Open PowerShell with 'Run as administrator' and run this again." }
Yes "Running as administrator"
if (-not (Get-Service -Name "SDIIntelligence" -ErrorAction SilentlyContinue)) {
    Stop-Here "This is not the SDI Intelligence server (no SDIIntelligence service). Run it on 10.0.0.5."
}
foreach ($name in $Services) {
    if (-not (Get-Service -Name $name -ErrorAction SilentlyContinue)) {
        Stop-Here "There is no $name service: SameDay is not installed here yet. Install-SameDay.ps1 comes first."
    }
}
$installed = $false
try { $installed = Test-Path -LiteralPath "$Target\brief_lite\lite_app.py" -ErrorAction Stop } catch { $installed = $false }
if (-not $installed) { Stop-Here "No $Target\brief_lite\lite_app.py - SameDay is not installed here yet." }
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { Stop-Here "git is not installed on this server." }
Yes "SameDay is installed and its services are here - SDI Intelligence will not be touched"
$before = RunningVersion
if ($before) { Say "Running now: $before" } else { Warn "SameDay is not answering at $Status right now." }

# -- 2. The code, from the repository ----------------------------------------------
Head "2. Fetching $Branch from sdi-sameday"
if (Test-Path -LiteralPath $Code) {
    if (-not (Test-Path -LiteralPath "$Code\.git")) { Stop-Here "$Code exists and is not this script's. Move it, or choose another with -Code." }
    $remote = (& git.exe -C $Code remote get-url origin 2>$null) -join ""
    if ($remote -ne $Repo) { Stop-Here "$Code belongs to another repository ($remote)." }
    if ((RunGit @("fetch", "-q", "origin", $Branch)) -ne 0) { Stop-Here "Could not fetch $Branch. Is the branch name right, and are you signed in as jbgray1874?" }
} else {
    & git.exe clone -q --branch $Branch $Repo $Code | Out-Host
    if ($LASTEXITCODE -ne 0) { Stop-Here "Could not clone sdi-sameday ($Branch). Sign in as jbgray1874 when asked." }
}
# The server's copy is never edited by hand: it is always exactly the branch.
if ((RunGit @("checkout", "-q", "-B", $Branch, "origin/$Branch")) -ne 0) { Stop-Here "Could not check out $Branch." }
if ((RunGit @("reset", "-q", "--hard", "origin/$Branch")) -ne 0) { Stop-Here "Could not match $Code to origin/$Branch." }
$commit = ((& git.exe -C $Code rev-parse --short HEAD) -join "").Trim()
$auto = "$Code\SDI_Automation"
if (-not (Test-Path -LiteralPath "$auto\brief_lite\lite_app.py")) { Stop-Here "The repository has no SDI_Automation\brief_lite\lite_app.py." }
$keyShape = 'sk-ant-[A-Za-z0-9_\-]{20,}|sk-proj-[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{32,}|xai-[A-Za-z0-9]{20,}'
$hits = @(Get-ChildItem -LiteralPath $auto -Recurse -File -Force | Select-String -Pattern $keyShape -CaseSensitive -ErrorAction SilentlyContinue)
if ($hits.Count) { Stop-Here "Key-shaped text in the repository ($($hits[0].Path)). Nothing was copied." }
$stamp = ""
if (Test-Path -LiteralPath "$auto\brief_lite\VERSION.txt") { $stamp = ((Get-Content -LiteralPath "$auto\brief_lite\VERSION.txt" -TotalCount 1) -join "").Trim() }
# What this server will report at /api/status: the stamp, the branch and the
# commit - so "is it running the new code?" has a yes or no answer.
$want = ("$stamp repo $Branch $commit").Trim()
Yes "Fetched $Branch at $commit"

# -- 3. Keep the code it replaces -----------------------------------------------
Head "3. Keeping a copy of the code being replaced"
$skipDirs = @(".git", "backups", ".venv", ".venv-gpu", "venv", "__pycache__", "out", "client_files", "studio_data", "logs")
$skipFiles = @(".env", "*.db", "*.db-wal", "*.db-shm", "*.npz", "*.pyc", "*.log", "PHONE_LINK.txt", "client_profiles.json")
$keep = "$Target\backups\before-update-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
# Code only: anything over 5 MB is not code, and the update never replaces it.
$robo = @($Target, $keep, "/E", "/MAX:5000000", "/R:1", "/W:1", "/NP", "/NFL", "/NDL", "/NJH", "/NJS") + @("/XD") + $skipDirs + @("/XF") + $skipFiles
& robocopy @robo | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Here "Could not keep a copy of the current code (robocopy $LASTEXITCODE)." }
Yes "Current code kept in $keep"

# -- 4. The new code in place ------------------------------------------------------
Head "4. Copying the new code into $Target"
$robo = @($auto, $Target, "/E", "/R:2", "/W:5", "/NP", "/NFL", "/NDL", "/NJH", "/NJS") + @("/XD") + $skipDirs + @("/XF") + $skipFiles
& robocopy @robo | Out-Null
if ($LASTEXITCODE -ge 8) {
    Write-Host "  [STOP]  The copy failed (robocopy $LASTEXITCODE) - the services were NOT restarted." -ForegroundColor Red
    Say "To put the old code back:  robocopy `"$keep`" `"$Target`" /E"
    exit 1
}
# ASCII, no byte-order mark: PowerShell 5.1's "UTF8" adds one, and the app
# reads this file as plain text.
[IO.File]::WriteAllLines("$Target\brief_lite\VERSION.txt", [string[]]@($want), (New-Object Text.ASCIIEncoding))
Yes "Copied - this will report: $want"

# -- 5. Restart and check -----------------------------------------------------------
Head "5. Restarting SameDay and checking it runs the new code (up to 2 minutes)"
foreach ($name in $Services) {
    try { Restart-Service -Name $name -Force -ErrorAction Stop; Yes "Restarted $name" }
    catch { Warn "Could not restart $name - $($_.Exception.Message)" }
}
$now = ""
$deadline = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $now = RunningVersion
    if ($now -eq $want) { break }
}
$craftUp = $false
try { $craftUp = (Invoke-WebRequest -Uri "http://localhost:5030/" -UseBasicParsing -TimeoutSec 10).StatusCode -eq 200 } catch { $craftUp = $false }
if ((Get-Service -Name "SDIIntelligence").Status -eq "Running") { Yes "SDI Intelligence is still running, untouched" }
else { Warn "SDI Intelligence is not running - this script did not touch it; check it separately." }

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($now -eq $want) {
    Write-Host "  SameDay is running the new code: $now" -ForegroundColor Green
    if (-not $craftUp) { Write-Host "  (SDI Craft on 5030 did not answer yet - check it in a minute.)" -ForegroundColor Yellow }
    Write-Host "  Open http://10.0.0.5:5020 in the office or on the VPN." -ForegroundColor White
} else {
    Write-Host "  SameDay is NOT answering with the new code yet." -ForegroundColor Yellow
    Say ("It reports: " + $(if ($now) { $now } else { "nothing - it is not answering" }))
    Say "The end of its log (keys removed):"
    SafeTail "$Target\logs\SDISameDay.log"
    Say "To put the old code back:"
    Say "  robocopy `"$keep`" `"$Target`" /E   then   Restart-Service SDISameDay, SDICraft"
}
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
