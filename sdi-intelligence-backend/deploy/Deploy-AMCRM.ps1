<#
    Deploy the AM CRM to SDI-App01 in one go.  RUN ON THE LAPTOP, VPN connected:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Deploy-AMCRM.ps1           # deploy
        .\sdi-intelligence-backend\deploy\Deploy-AMCRM.ps1 -Check    # show what would change, copy nothing

    What it does, and stops with a plain message if any step fails:
      1. Checks the server can be reached (FortiClient VPN connected).
      2. Gets the latest code (git pull of the AM CRM branch, from the "jbg" remote -
         where Claude pushes - when the laptop has it, otherwise from origin).
      3. Copies only the AM CRM files that differ from the server's copies.
      4. Restarts the SDIIntelligence service if a Python file changed, and waits for it;
         also the SDITrackerConnector service (AM CRM connector for ChatGPT / Claude) and
         the SDITTIConnector service (TTI despatch connector) once they exist, and the
         SDISplitScan service (delivery-note splitter) if its code changed.
      5. Checks the server's files now match the laptop's, byte for byte.

    Why: deploying by hand went wrong in the ways hands do - a dropped VPN left robocopy
    retrying for ever, a missed git pull copied old files, a restart run before the copy
    left the old code running. This does the steps in order and checks each one.

    Only the files listed in $Files are ever copied. The server's .env (its keys and
    settings) is never touched.
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [string]$Server = "10.0.0.5",
    [string]$Branch = "claude/app-portal-main-2026",
    [string]$Service = "SDIIntelligence",
    [string]$ConnectorService = "SDITrackerConnector",
    [string]$TtiConnectorService = "SDITTIConnector",
    [string]$SplitScanService = "SDISplitScan",
    # Which git remote to pull from. Default: "jbg" if the laptop has it, else "origin".
    [string]$Remote = "",
    # The server's backend folder; normally worked out from -Server. Set it only to
    # deploy to a different share (or a test folder).
    [string]$Destination = ""
)

# Native commands (git, sc.exe) write progress to stderr; under "Stop" Windows
# PowerShell 5.1 turns that into a terminating error. Errors are checked by hand.
$ErrorActionPreference = "Continue"

$Files = @(
    "voicecrm.py",
    "voicecrm_excel.py",
    "voicecrm_speech.py",
    "journal.py",
    "morning_review.py",
    "appportal/voice-crm.html",
    "voicecrm_connector.py",
    "connector_cards.py",
    "connector_oauth.py",
    "private_auth.py",
    "private_email.py",
    "private_email_routes.py",
    "private_email_integration.py",
    "private_draft_writer.py",
    "sue_despatch.py",
    "tracker_snapshot.py",
    "tti_despatch_routes.py",
    "tti_plan_source.py",
    "tti_data.py",
    "tti_search.py",
    "tti_files.py",
    "tools/tti_index_folders.py",
    "tti_connector.py",
    "connector_identity.py",
    "access.py",
    "appportal/tti-despatch.html",
    "appportal/guide-tti.html",
    "appportal/guide-am-crm.html",
    "appportal/estimating-pocket.html",
    "sdi_ops_routes.py",
    "appportal/sdi-remote-control.html",
    "private-email-readonly.html",
    "private-email.html",
    # The app portal's catalogue. Not Python, so it copies without a restart -
    # the service reads it from disk on each request.
    "services.json"
)
# app.py is deliberately NOT here. The server's copy has drifted from the repository
# before, and this script copies whole files: adding it would silently overwrite
# whatever is on the server with whatever is in the branch. Its two private-assistant
# edits are applied in place - see PRIVATE_ASSISTANT_SETUP.md section 3.
# The delivery-note splitter, which runs on the server as the SDISplitScan service. Paths
# from the repository root; they land in C:\ClaudeVision\tools\logistics on the server.
$ToolFiles = @(
    "tools/logistics/split_delivery_notes.py",
    "tools/logistics/delivery_note_reader.py",
    "tools/logistics/Install-SplitScanService.ps1"
)

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)      # C:\ClaudeVision
$src  = Join-Path $repo "sdi-intelligence-backend"
$dest = if ($Destination) { $Destination } else { "\\$Server\c$\ClaudeVision\sdi-intelligence-backend" }
$destRoot = Split-Path -Parent $dest                                   # \\server\c$\ClaudeVision

# Every file this deploys, as laptop path -> server path.
$Items = @()
foreach ($f in $Files) { $Items += [pscustomobject]@{ Name = $f; Src = (Join-Path $src $f); Dst = (Join-Path $dest $f) } }
foreach ($f in $ToolFiles) { $Items += [pscustomobject]@{ Name = $f; Src = (Join-Path $repo $f); Dst = (Join-Path $destRoot $f) } }

function Say([string]$Text, [string]$Colour = "Gray") { Write-Host "  $Text" -ForegroundColor $Colour }
function Stop-Deploy([string]$Text) {
    Write-Host ""
    Write-Host "  STOPPED: $Text" -ForegroundColor Red
    Write-Host ""
    exit 1
}
function Get-Sha([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return "" }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}
function Get-ServiceState([string]$Name = $Service) {
    if (-not (Get-Command sc.exe -ErrorAction SilentlyContinue)) { return "UNKNOWN: sc.exe not found" }
    $q = (& sc.exe "\\$Server" query $Name 2>&1) -join " "
    if ($q -match "STATE\s*:\s*\d+\s+(\w+)") { return $Matches[1] }
    if ($q -match "1060") { return "MISSING" }          # the service isn't installed
    return "UNKNOWN: $q"
}
function Show-ManualRestart([string]$Name = $Service) {
    Say "Restart it on the server instead (Remote Desktop, PowerShell as admin):" Yellow
    Write-Host ""
    Write-Host "      Restart-Service $Name -Force" -ForegroundColor White
    Write-Host "      Start-Sleep 8" -ForegroundColor White
    Write-Host "      Get-Service $Name | Format-Table Name, Status -AutoSize" -ForegroundColor White
    Write-Host ""
}
function Restart-One([string]$Name) {
    # Stop, wait, start, wait. True when it is RUNNING again.
    & sc.exe "\\$Server" stop $Name 2>&1 | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    do { Start-Sleep -Seconds 2; $state = Get-ServiceState $Name } until ($state -eq "STOPPED" -or (Get-Date) -gt $deadline)
    & sc.exe "\\$Server" start $Name 2>&1 | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    do { Start-Sleep -Seconds 2; $state = Get-ServiceState $Name } until ($state -eq "RUNNING" -or (Get-Date) -gt $deadline)
    if ($state -eq "RUNNING") { Start-Sleep -Seconds 6; return $true }
    Say "$Name did not come back as RUNNING (last state: $state)." Red
    Show-ManualRestart $Name
    return $false
}

Write-Host ""
Write-Host "AM CRM DEPLOY  ->  $Server" -ForegroundColor Cyan
Write-Host ("-" * 64)

# -- 1. Can we reach the server? -------------------------------------------------------
if (-not (Test-Path -LiteralPath $dest)) {
    Stop-Deploy "Can't reach $dest. Connect FortiClient VPN (we.are.sdi) and run this again."
}
Say "Server reachable." Green

# -- 2. Latest code -----------------------------------------------------------------------
Push-Location $repo
if (-not $Remote) {
    $Remote = if ((& git remote 2>&1) -contains "jbg") { "jbg" } else { "origin" }
}
$pull = & git pull $Remote $Branch 2>&1
$pullOk = ($LASTEXITCODE -eq 0)
$commit = ((& git rev-parse --short HEAD 2>&1) -join "").Trim()
Pop-Location
if (-not $pullOk) {
    Stop-Deploy ("git pull didn't work, so nothing was copied:`n" + (($pull | ForEach-Object { "    $_" }) -join "`n"))
}
Say "Latest code: commit $commit (from $Remote)." Green

# -- 3. What differs? ------------------------------------------------------------------------
$changed = @()
foreach ($i in $Items) {
    if (-not (Test-Path -LiteralPath $i.Src)) { Stop-Deploy "Missing on the laptop: $($i.Src)" }
    if ((Get-Sha $i.Src) -ne (Get-Sha $i.Dst)) { $changed += $i }
}
if ($changed.Count -eq 0) {
    Say "The server already has this version of the AM CRM. Nothing to do." Green
    Write-Host ""
    exit 0
}
Say "To update on the server:"
$changed | ForEach-Object { Say "    $($_.Name)" White }
if ($Check) {
    Say "Check only: nothing copied. Run again without -Check to deploy." Yellow
    Write-Host ""
    exit 0
}

# -- 4. Copy ---------------------------------------------------------------------------------
foreach ($i in $changed) {
    try {
        $folder = Split-Path -Parent $i.Dst
        if (-not (Test-Path -LiteralPath $folder)) { New-Item -ItemType Directory -Path $folder -Force -ErrorAction Stop | Out-Null }
        Copy-Item -LiteralPath $i.Src -Destination $i.Dst -Force -ErrorAction Stop
    } catch {
        Stop-Deploy "Copying $($i.Name) failed: $($_.Exception.Message). Check the VPN and run this again; it only copies what still differs."
    }
}
$bad = @($changed | Where-Object { (Get-Sha $_.Src) -ne (Get-Sha $_.Dst) })
if ($bad.Count -gt 0) { Stop-Deploy ("These didn't arrive intact: " + (($bad | ForEach-Object { $_.Name }) -join ", ") + ". Run this again.") }
Say ("Copied {0} file(s), checked byte for byte." -f $changed.Count) Green

# -- THE VERSION STAMP, OR THE SERVICE REPORTS THE WRONG ONE ------------------------------
#
# SDI-App01 is not a git clone - it is files copied onto it - so the service cannot ask git
# which commit it is running. It falls back to a .sdi-commit stamp (app.py _resolve_commit),
# which push-to-server.ps1 writes and this script did not. So X-SDI-Commit and /api/health
# went on naming whenever push-to-server last ran while the Python files beside them were
# current - and on 29 October that read as "the service does not have the fix" about a
# server that did. The header exists to end that guessing, so it has to be kept true.
#
# The second line records that this was a PARTIAL deploy. This script copies a named list
# and leaves app.py alone, so "the server is at commit X" is true of the AM CRM code and
# not necessarily of everything else; anyone reading the file should see that, and only the
# first line is read as the commit.
foreach ($stampDir in @($destRoot, $dest)) {
    try {
        $stampPath = Join-Path $stampDir ".sdi-commit"
        @($commit,
          "# Written by Deploy-AMCRM.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm'). PARTIAL deploy:",
          "# the AM CRM file list only - app.py and anything outside it are whatever",
          "# push-to-server.ps1 last copied. $($changed.Count) file(s) updated this run."
        ) | Set-Content -LiteralPath $stampPath -Encoding ASCII -ErrorAction Stop
    } catch {
        Say "Could not write $stampPath - /api/health will report a stale commit: $($_.Exception.Message)" Yellow
    }
}
Say "Version stamp updated, so /api/health reports $commit." Green

# -- app.py IS NOT COPIED, AND SILENCE ABOUT THAT COSTS A DEPLOY ---------------------------
#
# This script copies a named list and deliberately leaves app.py alone, because the server's
# copy has drifted before. push-to-server.ps1 copies the whole folder and DOES replace it.
# Two scripts, two file sets, and nothing said which one a change needed - so a change whose
# wiring lives in app.py deployed "successfully", restarted, and did nothing at all. That is
# exactly how the TTI despatch view landed on the server unmounted on 26 October 2026.
#
# It still does not copy it. It now says when that matters, which is the part that was free.
# The same trap applies to every backend file this script's list leaves out, not just
# app.py. The estimating API is the one that bites next: a change to estimate_routes.py
# or estimating_job_tools.py deploys "successfully" here, restarts, and is not on the
# server at all. Checked by name, because silence is what cost the afternoon.
$NotCopied = @("app.py", "estimate_routes.py", "estimating_job_tools.py",
               "public_surface.py", "auth.py", "config.py")
$missed = @()
foreach ($name in $NotCopied) {
    if ((Get-Sha (Join-Path $src $name)) -ne (Get-Sha (Join-Path $dest $name))) {
        $missed += $name
    }
}
if ($missed.Count -gt 0) {
    Write-Host ""
    Say "These differ from the server's copies, and this script does not copy them:" Yellow
    $missed | ForEach-Object { Say "    $_" White }
    Say "If your change is in one of those, it is NOT live. Deploy them with:" Yellow
    Write-Host ""
    Write-Host "      .\tools\start\push-to-server.ps1 -Apply" -ForegroundColor White
    Write-Host ""
    Say "That copies the whole backend folder, then restart the service." Yellow
}

# -- 5. Restart, if the server code changed ----------------------------------------------
$toolChanged = @($changed | Where-Object { $_.Name -like "tools/*.py" })
$pyChanged = @($changed | Where-Object { $_.Name -like "*.py" -and $_.Name -notlike "tools/*" })
$restarted = $false
if ($pyChanged.Count -gt 0) {
    Say "Restarting $Service (Python files changed)..."
    $state = Get-ServiceState
    if ($state -like "UNKNOWN*" -or $state -eq "MISSING") {
        Say "Couldn't control the service from the laptop ($state)." Yellow
        Show-ManualRestart
    } elseif (Restart-One $Service) {
        Say "$Service is running the new code." Green
        $restarted = $true
    }
    # The connector runs the same tracker code: restart it too, once it is installed
    # and running. Not installed (or switched off) is normal until it goes live.
    $cState = Get-ServiceState $ConnectorService
    if ($cState -eq "RUNNING") {
        Say "Restarting $ConnectorService..."
        if (Restart-One $ConnectorService) { Say "$ConnectorService is running the new code." Green }
        else { $restarted = $false }
    } elseif ($cState -ne "MISSING") {
        Say "$ConnectorService is $cState - left as it is." Gray
    }
    # The TTI connector (ChatGPT / Claude, chat and voice) runs the same TTI code as
    # the web view: restart it too, once it is installed. Not installed is normal
    # until it goes live.
    $tState = Get-ServiceState $TtiConnectorService
    if ($tState -eq "RUNNING") {
        Say "Restarting $TtiConnectorService..."
        if (Restart-One $TtiConnectorService) { Say "$TtiConnectorService is running the new code." Green }
        else { $restarted = $false }
    } elseif ($tState -ne "MISSING") {
        Say "$TtiConnectorService is $tState - left as it is." Gray
    }
} elseif ($toolChanged.Count -eq 0) {
    Say "Only the page changed: no restart needed." Green
}
# The splitter service: restarted when its code changed. Not installed yet is normal until
# Install-SplitScanService.ps1 has been run on the server.
if ($toolChanged.Count -gt 0) {
    $sState = Get-ServiceState $SplitScanService
    if ($sState -eq "RUNNING") {
        Say "Restarting $SplitScanService (splitter code changed)..."
        if (Restart-One $SplitScanService) { Say "$SplitScanService is running the new code." Green }
    } elseif ($sState -eq "MISSING") {
        Say "$SplitScanService is not installed yet. On the server, as admin:" Yellow
        Say "    C:\ClaudeVision\tools\logistics\Install-SplitScanService.ps1 -Source <UNC> -Out <UNC>" White
    } else {
        Say "$SplitScanService is $sState - left as it is." Gray
    }
}

# -- Done -------------------------------------------------------------------------------------
Write-Host ""
Write-Host ("DONE  -  commit {0}" -f $commit) -ForegroundColor Cyan
if (@($changed | Where-Object { $_.Name -eq "appportal/voice-crm.html" }).Count -gt 0) {
    Say "Ask users to close the app fully and reopen it to pick up the new page."
}
if ($pyChanged.Count -gt 0 -and -not $restarted) {
    Say "Not finished until the service is restarted (see above)." Yellow
    Write-Host ""
    exit 2
}
Write-Host ""
