<#
    RUN THIS ON THE LAPTOP, with FortiClient VPN (we.are.sdi) connected.
    Nothing else. It does not need to be run on the server, and it changes nothing.

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Check-AMCRM-Live.ps1

    It answers the questions that keep costing a round trip to ask:

        1. Does the LAPTOP's code have the AM CRM write fix?
        2. Does the SERVER's code have it?
        3. Which commit is the running service actually serving?
        4. Which .env files did it read, and are writes switched on?
        5. What has the tracker been doing, and how long is it taking?

    WHY IT IS ALL FROM THE LAPTOP
    Every one of these used to mean "run this on the server" - which meant Remote
    Desktop, and a question about which machine a command belonged to every time.
    The server's C: drive is already reachable over UNC (that is how the deploy
    copies files), so the laptop can read all of it. The one thing it cannot read
    that way is the service's own port, so it finds that in the service
    configuration rather than asking anybody to guess.

    It reports whether a setting is PRESENT. It never prints a value from .env.
#>
[CmdletBinding()]
param(
    [string]$Server = "10.0.0.5",
    # The commit that first carried the write fix. Anything containing it will do.
    [string]$FixCommit = "d85ddfee"
)

$ErrorActionPreference = "Continue"

$repo     = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # C:\ClaudeVision
$local    = Join-Path $repo "sdi-intelligence-backend"
$remote   = "\\$Server\c$\ClaudeVision\sdi-intelligence-backend"

function Head([string]$Text) {
    Write-Host ""
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ("-" * 68)
}
function Yes([string]$Text) { Write-Host "  [ok]   $Text" -ForegroundColor Green }
function No ([string]$Text) { Write-Host "  [NO]   $Text" -ForegroundColor Red }
function Hm ([string]$Text) { Write-Host "  [?]    $Text" -ForegroundColor Yellow }
function Say([string]$Text) { Write-Host "         $Text" -ForegroundColor Gray }

# The lines that exist only in the fixed version. Checked in the FILES rather
# than by commit, because the file on the server is the thing that runs - a
# commit says what should be there, a file says what is.
$Markers = @{
    "voicecrm_excel.py" = @("SESSION_SECONDS", "def reset_pool", "_session_is_gone")
    "voicecrm.py"       = @("[voicecrm.tracker]")
}

Write-Host ""
Write-Host "AM CRM - IS THE WRITE FIX LIVE?  ->  $Server" -ForegroundColor Cyan
Write-Host ("=" * 68)

# ── 1. Can the laptop see the server at all? ────────────────────────────────
Head "1. The server's files"
if (-not (Test-Path -LiteralPath $remote)) {
    No "Cannot reach $remote"
    Say "Connect FortiClient VPN (we.are.sdi) and run this again."
    Write-Host ""
    exit 1
}
Yes "Reachable over UNC: $remote"

# ── 2. The code, on both machines ───────────────────────────────────────────
Head "2. Does the code have the write fix?"
$laptopOk, $serverOk, $identical = $true, $true, $true
foreach ($file in $Markers.Keys) {
    $here  = Join-Path $local  $file
    $there = Join-Path $remote $file
    foreach ($pair in @(@{Where="laptop"; Path=$here}, @{Where="server"; Path=$there})) {
        if (-not (Test-Path -LiteralPath $pair.Path)) {
            No "$file is missing on the $($pair.Where)"
            if ($pair.Where -eq "laptop") { $laptopOk = $false } else { $serverOk = $false }
            continue
        }
        $text    = Get-Content -LiteralPath $pair.Path -Raw
        $missing = @($Markers[$file] | Where-Object { $text -notlike "*$_*" })
        if ($missing.Count -eq 0) {
            Yes "$file on the $($pair.Where): has the fix"
        } else {
            No  "$file on the $($pair.Where): OLD CODE (missing $($missing -join ', '))"
            if ($pair.Where -eq "laptop") { $laptopOk = $false } else { $serverOk = $false }
        }
    }
    if ((Test-Path -LiteralPath $here) -and (Test-Path -LiteralPath $there)) {
        $a = (Get-FileHash -LiteralPath $here  -Algorithm SHA256).Hash
        $b = (Get-FileHash -LiteralPath $there -Algorithm SHA256).Hash
        if ($a -ne $b) { $identical = $false; Hm "$file differs between laptop and server" }
    }
}
if ($identical) { Yes "The laptop's and the server's copies are byte for byte the same" }

if (-not $laptopOk) {
    Say ""
    Say "The LAPTOP does not have the fix, so a deploy would copy old code. Get it:"
    Write-Host "      git pull jbg claude/app-portal-main-2026" -ForegroundColor White
    Say "(jbg is github.com/jbgray1874 - the repository the fix is pushed to."
    Say " 'origin' on this laptop is a different repository, jbgraysdi2026.)"
}
elseif (-not $serverOk) {
    Say ""
    Say "The laptop has it and the SERVER does not. Deploy it:"
    Write-Host "      .\sdi-intelligence-backend\deploy\Deploy-AMCRM.ps1" -ForegroundColor White
}

# ── 3. Is the local checkout actually on the fix? ───────────────────────────
Head "3. This laptop's checkout"
Push-Location $repo
$branch = ((& git rev-parse --abbrev-ref HEAD 2>&1) -join "").Trim()
$commit = ((& git rev-parse --short HEAD 2>&1) -join "").Trim()
& git merge-base --is-ancestor $FixCommit HEAD 2>&1 | Out-Null
$contains = ($LASTEXITCODE -eq 0)
Pop-Location
Say "On branch '$branch', at commit $commit"
if ($contains) { Yes "This checkout contains $FixCommit (the write fix)" }
else {
    No "This checkout does NOT contain $FixCommit"
    Say "Run:  git pull jbg claude/app-portal-main-2026"
}

# ── 4. What is the service actually running? ─────────────────────────────────
Head "4. The running service"
$svc = Get-Service -ComputerName $Server -Name SDIIntelligence -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -eq "Running") { Yes "SDIIntelligence is $($svc.Status)" }
    else { No "SDIIntelligence is $($svc.Status)" }
} else { Hm "Could not read the service's state from here" }

# The port, from the service's own command line, so nobody has to guess it.
$port = ""
$nssmParams = ""
try {
    $key = "SYSTEM\CurrentControlSet\Services\SDIIntelligence\Parameters"
    $hive = [Microsoft.Win32.RegistryKey]::OpenRemoteBaseKey("LocalMachine", $Server)
    $sub  = $hive.OpenSubKey($key)
    if ($sub) {
        $nssmParams = [string]$sub.GetValue("AppParameters")
        $stdout     = [string]$sub.GetValue("AppStdout")
    }
} catch { }
if ($nssmParams -match "--port[= ]+(\d+)") { $port = $Matches[1] }
if ($port) { Yes "Listening on port $port  (from the service's own command line)" }
else { Hm "Could not read the port from the service configuration" }

if ($port) {
    try {
        $answer = Invoke-WebRequest "http://$Server`:$port/api/health" -UseBasicParsing -TimeoutSec 20
        $running = [string]$answer.Headers["X-SDI-Commit"]
        if ($running) { Yes "The service is serving commit: $running" }
        else { Hm "The service did not report a commit" }
        # Only compare when the commit is one this clone actually knows about.
        # A commit built on a machine whose work is not pulled here is unknown
        # to git, and treating "git cannot find it" as "it lacks the fix" would
        # be a false alarm - the file check in section 2 is the real answer.
        if ($running -match "^[0-9a-f]{7,40}$") {
            Push-Location $repo
            & git cat-file -e "$running^{commit}" 2>&1 | Out-Null
            $known = ($LASTEXITCODE -eq 0)
            if ($known) {
                & git merge-base --is-ancestor $FixCommit $running 2>&1 | Out-Null
                $liveHasFix = ($LASTEXITCODE -eq 0)
            }
            Pop-Location
            if (-not $known) {
                Hm "This clone does not know commit $running, so it cannot be compared"
                Say "Normal if it was built from a branch this laptop has not pulled."
                Say "Section 2 (the files on the server) is the answer that counts."
            } elseif ($liveHasFix) {
                Yes "That commit contains the write fix"
            } else {
                No "That commit does NOT contain the write fix"
                Say "The files may still be newer than the running process - restart it."
            }
        }
    } catch {
        Hm "Could not reach /api/health on port $port ($($_.Exception.Message))"
        Say "The file check in section 2 is the one that matters; this is a nicety."
    }
}

# ── 5. Settings, by name only ────────────────────────────────────────────────
Head "5. Is writing switched on? (names only - no values are printed)"
$envFiles = @(
    @{ What = "beside the service (wins)"; Path = Join-Path $remote ".env" },
    @{ What = "shared with the engine";    Path = "\\$Server\c$\ClaudeVision\.env" }
)
$seen = @{}
foreach ($f in $envFiles) {
    if (Test-Path -LiteralPath $f.Path) {
        Yes "Found: $($f.Path)   [$($f.What)]"
        foreach ($line in Get-Content -LiteralPath $f.Path) {
            if ($line -match "^\s*([A-Z0-9_]+)\s*=\s*(.*)$") {
                $name, $value = $Matches[1], $Matches[2].Trim()
                if (-not $seen.ContainsKey($name)) { $seen[$name] = [bool]$value }
            }
        }
    } else {
        Say "Not present: $($f.Path)   [$($f.What)]"
    }
}
foreach ($name in @("SDI_VOICECRM_WRITE", "SDI_VOICECRM_APPROVED_BY",
                    "SDI_VOICECRM_WRITERS", "SDI_VOICECRM_SITE",
                    "SDI_VOICECRM_XLSX", "SDI_VOICECRM_SHEET")) {
    if ($seen.ContainsKey($name) -and $seen[$name]) { Yes "$name is set" }
    elseif ($seen.ContainsKey($name)) { No "$name is present but EMPTY" }
    else { No "$name is not set in either .env" }
}
Say ""
Say "Nick cannot save a change unless SDI_VOICECRM_WRITE is yes, APPROVED_BY has"
Say "a name in it, and his email is in WRITERS. Any one missing is a polite"
Say "refusal, which looks exactly like the old bug. .env is read once at"
Say "startup, so a change there needs the service restarted."

# ── 6. The log ───────────────────────────────────────────────────────────────
Head "6. What the tracker has been doing"
$logPath = ""
if ($stdout) {
    # The service's own configured log, turned into a path the laptop can read.
    $logPath = $stdout -replace "^([A-Za-z]):", "\\$Server\`$1`$"
}
if ($logPath -and (Test-Path -LiteralPath $logPath)) {
    Say "Log: $logPath"
    $config = Select-String -LiteralPath $logPath -Pattern "\[config\]" | Select-Object -Last 1
    if ($config) { Say "Config it read: $($config.Line.Trim())" }
    $lines = Select-String -LiteralPath $logPath -Pattern "\[voicecrm\.tracker\]" |
             Select-Object -Last 12
    if ($lines) {
        Write-Host ""
        $lines | ForEach-Object { Write-Host "         $($_.Line.Trim())" -ForegroundColor White }
        Say ""
        Say "Send these lines to Claude. 'write ... outcome=saved' is a save that"
        Say "worked; 'outcome=not_saved' carries Microsoft's request id."
    } else {
        Say "No [voicecrm.tracker] lines yet. Expected until the new code has run"
        Say "and somebody has used the tracker."
    }
} else {
    Hm "Could not find the service's log from here"
    if ($stdout) { Say "The service says it writes to: $stdout" }
    Say "On the SERVER, over Remote Desktop:  & C:\Tools\nssm.exe get SDIIntelligence AppStdout"
}

# ── Verdict ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("=" * 68)
if ($laptopOk -and $serverOk) {
    Write-Host "  THE WRITE FIX IS ON THE SERVER." -ForegroundColor Green
    Write-Host "  If section 4 shows an older commit being served, restart the service:" -ForegroundColor Gray
    Write-Host "      Restart-Service -ComputerName $Server -Name SDIIntelligence -Force" -ForegroundColor White
    Write-Host "  Then, if section 5 is all green, Nick can be asked to save a change." -ForegroundColor Gray
} elseif ($laptopOk) {
    Write-Host "  THE FIX IS ON THIS LAPTOP BUT NOT ON THE SERVER. Deploy it." -ForegroundColor Yellow
} else {
    Write-Host "  THIS LAPTOP DOES NOT HAVE THE FIX. Pull it first (section 2)." -ForegroundColor Red
}
Write-Host ("=" * 68)
Write-Host ""
