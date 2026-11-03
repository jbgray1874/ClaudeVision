<#
    Deploy the portal's estimating code to SDI-App01, from the laptop. No git on the server.
    RUN ON THE LAPTOP, on the office network or VPN, AFTER the laptop has pulled and merged:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Deploy-Estimating.ps1 -Check   # show what would change
        .\sdi-intelligence-backend\deploy\Deploy-Estimating.ps1          # deploy

    WHY (D-647). The phone reaches SDI-App01 through Microsoft's App Proxy, never the laptop.
    SDI-App01 runs its own copy of the portal, and its copy decides what a phone may do: an old
    copy refuses the self-running switch with "That action is only available on the office
    network". The server has no git, so its copy is updated the way Deploy-AMCRM.ps1 updates
    the AM CRM: by copying from the laptop's checkout, which is the code the laptop already runs.

    What it does, in order, stopping with a plain message if a step fails:
      1. Checks the server's folder can be reached.
      2. Checks the laptop holds the commits it is meant to carry (-Commits).
      3. Refuses if the backend's requirements.txt differs from the server's: new code that
         needs a package the server lacks would stop the service, and with it the AM CRM and
         HR apps. Install the packages on the server first, then run this again.
      4. Lists every code file (.py .html .js .css .webmanifest) that differs. -Check stops here.
      5. Backs up every server file it will replace, to
         \\<server>\c$\ClaudeVision\deploy-backups\estimating-<time>\
      6. Copies, and checks each file byte for byte.
      7. Restarts the SDIIntelligence service and waits for it to answer on its port.
      8. If it does not come back: puts every backed-up file back, removes the files it added,
         restarts again, and says so. The server is left as it was.

    Never touched: .env (keys and settings), .venv, logs, state, tests, docs.
    ASCII ONLY, like the other scripts here.
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [string]$Server = "10.0.0.5",
    [int]$Port = 8071,
    [string]$Service = "SDIIntelligence",
    # The commits the server must end up with: the phone's self-running switch (portal,
    # 48ff715f) and the engine side the laptop merged (1e065597).
    [string[]]$Commits = @("48ff715f", "1e065597"),
    [string]$Destination = ""
)
$ErrorActionPreference = "Continue"

$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)      # C:\ClaudeVision
$src  = Join-Path $repo "sdi-intelligence-backend"
$dest = if ($Destination) { $Destination } else { "\\$Server\c$\ClaudeVision\sdi-intelligence-backend" }
$backupRoot = Join-Path (Split-Path -Parent $dest) "deploy-backups"

# Code only. Folders never copied, whatever they hold.
$Extensions = @(".py", ".html", ".js", ".css", ".webmanifest")
$SkipDirs   = @(".venv", "venv", "__pycache__", "tests", "docs", "env", "logs", "state",
                "deploy", "proof_connector", ".git", "node_modules")

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
function Get-ServiceState {
    $q = (& sc.exe "\\$Server" query $Service 2>&1) -join " "
    if ($q -match "STATE\s*:\s*\d+\s+(\w+)") { return $Matches[1] }
    if ($q -match "1060") { return "MISSING" }
    return "UNKNOWN: $q"
}
function Test-Answers {
    # Any HTTP reply - a 401 included - means the service is up: every reply carries
    # X-SDI-Commit. Only no reply at all is down.
    try {
        $r = Invoke-WebRequest -Uri "http://${Server}:$Port/api/health" -UseBasicParsing -TimeoutSec 10
        return $true
    } catch {
        if ($_.Exception.Response) { return $true }
        return $false
    }
}
function Restart-AndWait {
    & sc.exe "\\$Server" stop $Service 2>&1 | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    do { Start-Sleep -Seconds 2; $state = Get-ServiceState } until ($state -eq "STOPPED" -or (Get-Date) -gt $deadline)
    & sc.exe "\\$Server" start $Service 2>&1 | Out-Null
    $deadline = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Seconds 3
        $state = Get-ServiceState
        $up = ($state -eq "RUNNING") -and (Test-Answers)
    } until ($up -or (Get-Date) -gt $deadline)
    return $up
}
function Get-CodeFiles([string]$Root) {
    $rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd("\")
    Get-ChildItem -LiteralPath $Root -Recurse -File | Where-Object {
        $rel = $_.FullName.Substring($rootFull.Length + 1)
        $parts = $rel -split "[\\/]"
        ($Extensions -contains $_.Extension.ToLower()) -and
        -not ($parts[0..($parts.Count - 2)] | Where-Object { $SkipDirs -contains $_ }) -and
        -not ($_.Name -like ".env*")
    } | ForEach-Object { $_.FullName.Substring($rootFull.Length + 1) }
}

Write-Host ""
Write-Host "ESTIMATING DEPLOY  ->  $Server" -ForegroundColor Cyan
Write-Host ("-" * 64)

# -- 1. Can we reach the server? ----------------------------------------------------------
if (-not (Test-Path -LiteralPath $dest)) {
    Stop-Deploy "Can't reach $dest. Connect to the office network or FortiClient VPN, and check this account can open \\$Server\c$."
}
Say "Server folder reachable: $dest" Green

# -- 2. The laptop holds the commits ------------------------------------------------------
Push-Location $repo
foreach ($c in $Commits) {
    & git merge-base --is-ancestor $c HEAD 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Pop-Location
        Stop-Deploy "The laptop does not hold commit $c yet. Run the laptop's pull commands first (both checks must print 'fixes in'), then this."
    }
}
$commit = ((& git rev-parse --short HEAD 2>&1) -join "").Trim()
Pop-Location
Say "Laptop code: commit $commit (holds $($Commits -join ', '))." Green

# -- 3. Same packages ---------------------------------------------------------------------
$reqSrc  = Join-Path $src "requirements.txt"
$reqDest = Join-Path $dest "requirements.txt"
if ((Test-Path -LiteralPath $reqSrc) -and (Get-Sha $reqSrc) -ne (Get-Sha $reqDest)) {
    $want = @(Get-Content -LiteralPath $reqSrc | Where-Object { $_ -and -not $_.StartsWith("#") })
    $have = @(if (Test-Path -LiteralPath $reqDest) { Get-Content -LiteralPath $reqDest } else { @() })
    $new  = @($want | Where-Object { $have -notcontains $_ })
    Stop-Deploy ("The backend's requirements.txt differs from the server's, so the new code may need packages the server does not have. Nothing was copied. On the server, in C:\ClaudeVision\sdi-intelligence-backend, run:`n      .\.venv\Scripts\python.exe -m pip install -r requirements.txt`n  after copying requirements.txt across, then run this again." +
                 $(if ($new.Count) { "`n  Lines the server's file lacks: " + ($new -join "; ") } else { "" }))
}
Say "Packages: requirements.txt matches the server's." Green

# -- 4. What differs? ---------------------------------------------------------------------
$files = @(Get-CodeFiles $src)
$changed = @($files | Where-Object { (Get-Sha (Join-Path $src $_)) -ne (Get-Sha (Join-Path $dest $_)) })
if ($changed.Count -eq 0) {
    Say "The server already has this code. Nothing to do." Green
    Write-Host ""
    exit 0
}
Say ("{0} file(s) to update on the server:" -f $changed.Count)
$changed | ForEach-Object { Say "    $_" White }
if ($Check) {
    Say "Check only: nothing copied. Run again without -Check to deploy." Yellow
    Write-Host ""
    exit 0
}

# -- 5. Back up what will be replaced -------------------------------------------------------
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $backupRoot "estimating-$stamp"
$added = @()
foreach ($f in $changed) {
    $d = Join-Path $dest $f
    if (Test-Path -LiteralPath $d) {
        $b = Join-Path $backup $f
        try {
            New-Item -ItemType Directory -Path (Split-Path -Parent $b) -Force | Out-Null
            Copy-Item -LiteralPath $d -Destination $b -Force -ErrorAction Stop
        } catch {
            Stop-Deploy "Backing up $f failed: $($_.Exception.Message). Nothing was copied."
        }
    } else {
        $added += $f
    }
}
Say "Backed up the server's copies to $backup" Green

function Undo-Deploy {
    Say "Putting the server back as it was..." Yellow
    foreach ($f in $changed) {
        $b = Join-Path $backup $f
        if (Test-Path -LiteralPath $b) { Copy-Item -LiteralPath $b -Destination (Join-Path $dest $f) -Force }
    }
    foreach ($f in $added) { Remove-Item -LiteralPath (Join-Path $dest $f) -Force -ErrorAction SilentlyContinue }
    if (Restart-AndWait) { Say "Rolled back: the server is running its previous code." Yellow }
    else {
        Say "Rolled back the files, but $Service did not come back. On the server (Remote Desktop, PowerShell as admin):" Red
        Write-Host "      Restart-Service $Service -Force" -ForegroundColor White
        Write-Host "      Get-Content C:\ClaudeVision\output\logs\*.log -Tail 40" -ForegroundColor White
    }
}

# -- 6. Copy ------------------------------------------------------------------------------
foreach ($f in $changed) {
    try {
        $d = Join-Path $dest $f
        New-Item -ItemType Directory -Path (Split-Path -Parent $d) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $src $f) -Destination $d -Force -ErrorAction Stop
    } catch {
        Say "Copying $f failed: $($_.Exception.Message)" Red
        Undo-Deploy
        Stop-Deploy "The copy did not finish, so the server was put back."
    }
}
$bad = @($changed | Where-Object { (Get-Sha (Join-Path $src $_)) -ne (Get-Sha (Join-Path $dest $_)) })
if ($bad.Count -gt 0) {
    Undo-Deploy
    Stop-Deploy ("These did not arrive intact: " + ($bad -join ", ") + ". The server was put back.")
}
Say ("Copied {0} file(s), checked byte for byte." -f $changed.Count) Green

# -- 7. Restart and check it answers -------------------------------------------------------
$state = Get-ServiceState
if ($state -like "UNKNOWN*" -or $state -eq "MISSING") {
    Say "Couldn't control $Service from the laptop ($state). The files are copied; restart it on the server:" Yellow
    Write-Host "      Restart-Service $Service -Force" -ForegroundColor White
    Write-Host "  If it does not start, the backup to restore is $backup" -ForegroundColor Yellow
    exit 2
}
Say "Restarting $Service and waiting for it to answer on port $Port..."
if (-not (Restart-AndWait)) {
    Say "$Service did not come back on the new code." Red
    Undo-Deploy
    Stop-Deploy "The new code did not start on the server, so it was rolled back. Send the last lines of C:\ClaudeVision\output\logs on the server."
}

Write-Host ""
Write-Host ("DONE  -  SDI-App01 is running commit {0}" -f $commit) -ForegroundColor Cyan
Say "Ask phone users to close the app fully and reopen it to pick up the new pages."
Write-Host ""
