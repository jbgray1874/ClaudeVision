<#
    UPDATE SDI SAMEDAY ON THE SERVER FROM ITS PRIVATE REPOSITORY.

    Run FROM THE LAPTOP, VPN connected, the same way as Ship-It:

        cd C:\ClaudeVision
        git pull jbg claude/app-portal-main-2026
        .\sdi-intelligence-backend\deploy\Update-SameDay.ps1 -Branch claude/inspiring-planck-8juriz

    Without -Branch it takes main. The first time, a GitHub sign-in window
    may open: sign in as jbgray1874, the account the private repository
    belongs to.

    -- WHY FROM THE LAPTOP ---------------------------------------------------
    4 November 2026: run on the server it stopped at "git is not installed on
    this server". The server has no git, and needs none: like Ship-It, this
    fetches the code on the laptop and copies it over the server's admin share
    (\\10.0.0.5\c$), then restarts the services with sc.exe.

    -- WHY NOT UPDATE_SAME_DAY.bat ON THE SERVER -----------------------------
    Muhammad's batch file copies K: (the older code) and starts a second copy
    of SameDay outside its service, which fights the service for port 5020.

    -- WHAT IT CHANGES -----------------------------------------------------------
    The code in C:\SDI_Automation on the server, then it restarts SDISameDay
    and SDICraft. The code it replaces is kept first, in
    C:\SDI_Automation\backups\ on the server, and the end of the run says how
    to put it back.

    -- WHAT IT NEVER TOUCHES -----------------------------------------------------
    The keys (.env), the chats (lite.db), Craft's log, renders and uploads
    (out\, client_files\), the spend log (studio_data\), logs, the Python
    packages (.venv-gpu), K:, and every other service - SDIIntelligence
    included. The repository holds no data, so there is none to copy over.
#>
[CmdletBinding()]
param(
    [string]$Branch = "main",
    [string]$Server = "10.0.0.5",
    [string]$Repo = "https://jbgray1874@github.com/jbgray1874/sdi-sameday.git",
    # The laptop's own copy of the repository for this, used for nothing else
    # (C:\SameDayRepo belongs to Publish-SameDay-Code.ps1, which empties it).
    [string]$Code = "C:\SameDayDeploy"
)

$ErrorActionPreference = "Continue"
$Target = "\\$Server\c$\SDI_Automation"
$Services = @("SDISameDay", "SDICraft")
$Version = "http://${Server}:5020/api/version"

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
function Get-ServiceState([string]$Name) {
    $q = (& sc.exe "\\$Server" query $Name 2>&1) -join " "
    if ($q -match "STATE\s*:\s*\d+\s+(\w+)") { return $Matches[1] }
    if ($q -match "1060") { return "MISSING" }
    return "UNKNOWN: $q"
}
function Restart-One([string]$Name) {
    # Stop, wait, start, wait. True when it is RUNNING again.
    & sc.exe "\\$Server" stop $Name 2>&1 | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    do { Start-Sleep -Seconds 2; $state = Get-ServiceState $Name } until ($state -eq "STOPPED" -or (Get-Date) -gt $deadline)
    & sc.exe "\\$Server" start $Name 2>&1 | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    do { Start-Sleep -Seconds 2; $state = Get-ServiceState $Name } until ($state -eq "RUNNING" -or (Get-Date) -gt $deadline)
    return ($state -eq "RUNNING")
}
$script:Answer = $null
function RunningVersion {
    try { $script:Answer = Invoke-RestMethod -Uri $Version -TimeoutSec 5; return [string]$script:Answer.version }
    catch { return "" }
}
# A log tail fit to be pasted into chat: anything key-shaped is removed first.
function SafeTail([string]$Path, [int]$Lines = 20) {
    if (-not (Test-Path -LiteralPath $Path)) { Say "(no log at $Path)"; return }
    foreach ($line in (Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue)) {
        Say ($line -replace 'sk-[A-Za-z0-9_\-]{16,}|xai-[A-Za-z0-9]{16,}', '[key removed]')
    }
}

Write-Host ""
Write-Host "  SDI SAMEDAY - UPDATE FROM ITS REPOSITORY ($Branch)  ->  $Server" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')" -ForegroundColor DarkGray

# -- 1. Checks: git here, the server reachable, SameDay installed there ---------------
Head "1. Checks before anything is changed"
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
    Stop-Here "git is not installed on this computer. Run this on the laptop, where Ship-It runs."
}
Yes "git is here"
# FAIL CLOSED: an error inside an if's condition makes PowerShell skip the if.
$installed = $false
try { $installed = Test-Path -LiteralPath "$Target\brief_lite\lite_app.py" -ErrorAction Stop } catch { $installed = $false }
if (-not $installed) {
    Stop-Here "Can't reach $Target\brief_lite\lite_app.py. Connect FortiClient VPN (or be in the office) and run this again."
}
Yes "The server's SameDay folder is reachable ($Target)"
foreach ($name in $Services) {
    $state = Get-ServiceState $name
    if ($state -eq "MISSING") { Stop-Here "There is no $name service on ${Server} - Install-SameDay.ps1 comes first." }
    if ($state -like "UNKNOWN*") { Stop-Here "Can't ask $Server about $name ($state). This needs the same rights Ship-It uses." }
}
Yes "SDISameDay and SDICraft are there - SDI Intelligence will not be touched"
$before = RunningVersion
if ($before) { Say "Running now: $before" } else { Say "Running now: (an older SameDay that does not say its version)" }

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
# This copy is never edited by hand: it is always exactly the branch.
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
# What the server will report: the stamp, the branch and the commit - so "is
# it running the new code?" has a yes or no answer.
$want = ("$stamp repo $Branch $commit").Trim()
Yes "Fetched $Branch at $commit"

# -- 3. Keep the code it replaces -----------------------------------------------
Head "3. Keeping a copy of the code being replaced (on the server)"
$skipDirs = @(".git", "backups", ".venv", ".venv-gpu", "venv", "__pycache__", "out", "client_files", "studio_data", "logs")
$skipFiles = @(".env", "*.db", "*.db-wal", "*.db-shm", "*.npz", "*.pyc", "*.log", "PHONE_LINK.txt", "client_profiles.json")
$keep = "$Target\backups\before-update-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
# Code only: anything over 5 MB is not code, and the update never replaces it.
$robo = @($Target, $keep, "/E", "/MAX:5000000", "/R:1", "/W:1", "/NP", "/NFL", "/NDL", "/NJH", "/NJS") + @("/XD") + $skipDirs + @("/XF") + $skipFiles
& robocopy @robo | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Here "Could not keep a copy of the current code (robocopy $LASTEXITCODE)." }
Yes "Current code kept in $keep"

# -- 4. The new code in place ------------------------------------------------------
Head "4. Copying the new code to $Target"
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
Yes "Copied - it will report: $want"

# -- 5. Restart and check -----------------------------------------------------------
Head "5. Restarting SameDay and checking it runs the new code (up to 2 minutes)"
foreach ($name in $Services) {
    if (Restart-One $name) { Yes "Restarted $name" } else { Warn "$name did not come back as RUNNING" }
}
$now = ""
$deadline = (Get-Date).AddSeconds(150)
while ((Get-Date) -lt $deadline) {
    $now = RunningVersion
    if ($now -eq $want) { break }
    Start-Sleep -Seconds 5
}
$intel = Get-ServiceState "SDIIntelligence"
if ($intel -eq "RUNNING") { Yes "SDI Intelligence is still running, untouched" }
else { Warn "SDI Intelligence reports $intel - this script did not touch it; check it separately." }

Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($now -eq $want) {
    Write-Host "  SameDay is running the new code: $now" -ForegroundColor Green
    # Past work: can SameDay itself (the service) read the drives its indexes point at?
    $reads = $script:Answer.can_read
    if ($reads) {
        foreach ($d in @("W", "S", "K")) {
            $ok = [bool]$reads.$d
            Write-Host ("    SameDay can read ${d}:  " + $(if ($ok) { "yes" } else { "NO" })) -ForegroundColor $(if ($ok) { "Green" } else { "Yellow" })
        }
        if (-not $reads.W) {
            Write-Host "  W: is where past jobs live. Its log says why it could not be mapped:" -ForegroundColor Yellow
            Say "Select-String 'drive W' \\$Server\c$\SDI_Automation\logs\SDISameDay.log | Select-Object -Last 1"
            Say "If the name is wrong, set LITE_DRIVES in C:\SDI_Automation\.env; if it is access denied, the"
            Say "service account needs read access to the share (send Claude the line)."
        }
    }
    # Past work (4 Nov 2026, "it keeps saying it can't see past jobs"): what SameDay can find. It searches indexes
    # made from W: and K: (projects.db, knowledge.db, all_img_index.npz), not the drives file by file. The job
    # index loads in the first seconds after a start.
    $past = $script:Answer.past_work
    $until = (Get-Date).AddSeconds(60)
    while ($past -and ([string]$past.why -match "job index still loading") -and (Get-Date) -lt $until) {
        Start-Sleep -Seconds 5
        [void](RunningVersion)
        $past = $script:Answer.past_work
    }
    if ($past) {
        $jobs = [int]$past.jobs
        if ($jobs -gt 0) { Write-Host ("    Past jobs it can find:  " + $jobs) -ForegroundColor Green }
        else { Write-Host ("    Past jobs it can find:  NONE - " + $past.why) -ForegroundColor Yellow }
        if ($past.estimates) { Write-Host "    Old estimates (K:):     yes" -ForegroundColor Green }
        else { Write-Host "    Old estimates (K:):     NO - no knowledge.db" -ForegroundColor Yellow }
        if ($past.pictures) { Write-Host "    Look-alike pictures:    yes" -ForegroundColor Green }
        elseif ($jobs -gt 0) { Write-Host ("    Look-alike pictures:    off (" + $past.why + ") - past jobs are still found by number, name and words") -ForegroundColor Gray }
        if ($jobs -le 0 -or -not $past.estimates) {
            Write-Host "  The index files are made on Muhammad's laptop from W: and K:. Copy them to the server:" -ForegroundColor Yellow
            Say "projects.db and knowledge.db into \\$Server\c$\SDI_Automation\brief_lite\ (and all_img_index.npz"
            Say "into \\$Server\c$\SDI_Automation\, from the same day), then: Restart-Service SDISameDay on the server."
        }
    } else {
        Say "(This SameDay does not report its past work yet.)"
    }
    Write-Host "  Next, if SDI Intelligence has changed too: Ship-It." -ForegroundColor White
} else {
    Write-Host "  SameDay is NOT answering with the new code yet." -ForegroundColor Yellow
    Say ("It reports: " + $(if ($now) { $now } else { "nothing at $Version" }))
    Say "The end of its log (keys removed):"
    SafeTail "$Target\logs\SDISameDay.log"
    Say "To put the old code back (from this laptop):"
    Say "  robocopy `"$keep`" `"$Target`" /E   then run this script's restart again, or on the server:"
    Say "  Restart-Service SDISameDay, SDICraft"
}
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
