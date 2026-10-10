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
         also the SDITrackerConnector service (ChatGPT / Claude connector) once it exists.
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
    "connector_cards.py"
)

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)      # C:\ClaudeVision
$src  = Join-Path $repo "sdi-intelligence-backend"
$dest = if ($Destination) { $Destination } else { "\\$Server\c$\ClaudeVision\sdi-intelligence-backend" }

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
foreach ($f in $Files) {
    $s = Join-Path $src $f
    if (-not (Test-Path -LiteralPath $s)) { Stop-Deploy "Missing on the laptop: $s" }
    if ((Get-Sha $s) -ne (Get-Sha (Join-Path $dest $f))) { $changed += $f }
}
if ($changed.Count -eq 0) {
    Say "The server already has this version of the AM CRM. Nothing to do." Green
    Write-Host ""
    exit 0
}
Say "To update on the server:"
$changed | ForEach-Object { Say "    $_" White }
if ($Check) {
    Say "Check only: nothing copied. Run again without -Check to deploy." Yellow
    Write-Host ""
    exit 0
}

# -- 4. Copy ---------------------------------------------------------------------------------
foreach ($f in $changed) {
    try {
        Copy-Item -LiteralPath (Join-Path $src $f) -Destination (Join-Path $dest $f) -Force -ErrorAction Stop
    } catch {
        Stop-Deploy "Copying $f failed: $($_.Exception.Message). Check the VPN and run this again; it only copies what still differs."
    }
}
$bad = @($changed | Where-Object { (Get-Sha (Join-Path $src $_)) -ne (Get-Sha (Join-Path $dest $_)) })
if ($bad.Count -gt 0) { Stop-Deploy ("These didn't arrive intact: " + ($bad -join ", ") + ". Run this again.") }
Say ("Copied {0} file(s), checked byte for byte." -f $changed.Count) Green

# -- 5. Restart, if the server code changed ----------------------------------------------
$pyChanged = @($changed | Where-Object { $_ -like "*.py" })
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
} else {
    Say "Only the page changed: no restart needed." Green
}

# -- Done -------------------------------------------------------------------------------------
Write-Host ""
Write-Host ("DONE  -  commit {0}" -f $commit) -ForegroundColor Cyan
if ($changed -contains "appportal/voice-crm.html") {
    Say "Ask users to close the app fully and reopen it to pick up the new page."
}
if ($pyChanged.Count -gt 0 -and -not $restarted) {
    Say "Not finished until the service is restarted (see above)." Yellow
    Write-Host ""
    exit 2
}
Write-Host ""
