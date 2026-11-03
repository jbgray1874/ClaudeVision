<#
    SDI SAMEDAY INTELLIGENCE - install it on the server, INTERNAL ONLY.

    Run ON THE SERVER (10.0.0.5), over Remote Desktop, in PowerShell (not
    the ISE) opened with "Run as administrator".
    First copy this one file across, FROM THE LAPTOP:

        Copy-Item C:\ClaudeVision\sdi-intelligence-backend\deploy\Install-SameDay.ps1 \\10.0.0.5\c$\Tools\

    then, on the server:

        powershell -ExecutionPolicy Bypass -File C:\Tools\Install-SameDay.ps1

    -- WHAT IT ADDS - ALL NEW ------------------------------------------------
    "a new application called sameday ... with its own existence ... it's not
    to over ride anything in there already" - James Gray, 3 November 2026.

      C:\SDI_Automation                  its own folder, copied from K:
      C:\Program Files\Python311         its own Python 3.11, ONLY if missing,
                                         installed with PATH, the py launcher
                                         and file types left exactly as they are
      C:\SDI_Automation\.venv-gpu        its own packages (CPU torch: no GPU)
      services SDISameDay and SDICraft   ports 5020 and 5030, LocalSystem,
                                         restarted by NSSM if they stop
      two firewall rules                 5020 and 5030, from private (office
                                         and VPN) addresses only

    -- WHAT IT NEVER TOUCHES -------------------------------------------------
    The SDIIntelligence service and its port 8071, C:\ClaudeVision, any other
    service, any existing firewall rule, PATH. It refuses to run over an
    existing install unless asked to -Update, and an update never overwrites
    the server's own data: chats, uploads, renders, spend log or keys.

    -- INTERNAL ONLY, AND WHAT THAT MEANS ------------------------------------
    No Entra work (3 November). People open http://10.0.0.5:5020 in the office
    or on the VPN and use the team code. Browsers allow the microphone only on
    https pages, so voice waits for the App Proxy step; typed briefs, files,
    renders, GAs and the PDFs all work.
#>
[CmdletBinding()]
param(
    # K: is \\sdi-dc01\shareddata$\Shared on the laptop (Check-SameDay-Ready,
    # 3 November). A drive letter would not exist here; the UNC name does.
    [string]$Source = "\\sdi-dc01\shareddata$\Shared\IT\AI & Automation\Design\SDI Same Day Intelligence\SDI_Automation",
    [string]$Target = "C:\SDI_Automation",
    [string]$Nssm = "C:\Tools\nssm.exe",
    # Private address ranges: the office network and the VPN. The server takes
    # nothing in from the internet, so these are the only callers there are.
    [string[]]$AllowFrom = @("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"),
    # Copy new code over an existing install, keeping the server's own data.
    [switch]$Update
)

$ErrorActionPreference = "Stop"
$Python = "C:\Program Files\Python311\python.exe"
$PythonUrl = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
$Venv = Join-Path $Target ".venv-gpu"
$Logs = Join-Path $Target "logs"
$Apps = @(
    @{ Name = "SDISameDay"; Script = "brief_lite\lite_app.py"; Port = 5020;
       Display = "SDI SameDay Intelligence"; Probe = "/api/status" },
    @{ Name = "SDICraft";   Script = "craft\craft_site.py";   Port = 5030;
       Display = "SDI Craft (SameDay)";      Probe = "/" }
)

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
    Write-Host "          Nothing after this point was done." -ForegroundColor Red
    Write-Host ""
    exit 1
}
function Listening([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}
function Reachable([string]$HostName, [int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $wait = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $wait.AsyncWaitHandle.WaitOne(4000)) { return $false }
        $client.EndConnect($wait)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}
# NSSM, with its exit code checked: a setting that silently failed is a
# service that silently behaves differently.
function Nssm([string[]]$Arguments) {
    & $Nssm @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { Stop-Here "nssm $($Arguments -join ' ') failed (exit $LASTEXITCODE)." }
}
# A log tail fit to be pasted into chat: anything key-shaped is removed first.
function SafeTail([string]$Path, [int]$Lines = 20) {
    if (-not (Test-Path -LiteralPath $Path)) { Say "(no log yet at $Path)"; return }
    foreach ($line in (Get-Content -LiteralPath $Path -Tail $Lines -ErrorAction SilentlyContinue)) {
        Say ($line -replace 'sk-[A-Za-z0-9_\-]{16,}|xai-[A-Za-z0-9]{16,}', '[key removed]')
    }
}

Write-Host ""
Write-Host "  SDI SAMEDAY INTELLIGENCE - INSTALL (internal only)" -ForegroundColor White
Write-Host "  $(Get-Date -Format 'dddd d MMMM yyyy, HH:mm')$(if ($Update) { '  -  UPDATE' })" -ForegroundColor DarkGray

# -- 1. Is this the right machine, and is it safe to start? --------------------
Head "1. Checks before anything is changed"
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Stop-Here "Open PowerShell with 'Run as administrator' and run this again." }
Yes "Running as administrator"

if (-not (Get-Service -Name "SDIIntelligence" -ErrorAction SilentlyContinue) -or
    -not (Test-Path -LiteralPath $Nssm)) {
    Stop-Here "This is not the SDI Intelligence server (no SDIIntelligence service, or no $Nssm). Run it on 10.0.0.5."
}
Yes "This is the SDI Intelligence server - and that service will not be touched"

if (-not (Test-Path -LiteralPath (Join-Path $Source "brief_lite\lite_app.py"))) {
    Stop-Here "Cannot read $Source from here. Check the path, and that this account can read K:'s share."
}
Yes "Can read SameDay's folder on K: ($Source)"

$installed = Test-Path -LiteralPath $Target
if ($installed -and -not $Update) {
    Stop-Here "$Target already exists. To copy new code over it, keeping the server's data: add -Update."
}
if (-not $installed -and $Update) {
    Stop-Here "-Update asked for, but $Target is not installed yet. Run without -Update."
}
foreach ($app in $Apps) {
    $svc = Get-Service -Name $app.Name -ErrorAction SilentlyContinue
    if ($svc -and -not $Update) { Stop-Here "A service called $($app.Name) already exists." }
    if (-not $svc -and (Listening $app.Port)) {
        Stop-Here "Something else is already listening on port $($app.Port). Nothing will be put on top of it."
    }
}
Yes "Folder, service names and ports are free (or this is an update of SameDay's own)"

foreach ($api in @("api.openai.com", "api.anthropic.com")) {
    if (Reachable $api 443) { Yes "The server can reach $api" }
    else { Warn "The server cannot reach $api on 443 - SameDay's AI calls would fail. Ask IT to allow it." }
}

# -- 2. Python 3.11, beside whatever else is installed -------------------------
Head "2. Python 3.11"
if (Test-Path -LiteralPath $Python) {
    Yes "Already installed: $Python"
} else {
    Say "Downloading Python 3.11.9 (64-bit) from python.org..."
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $installer = Join-Path $env:TEMP "python-3.11.9-amd64.exe"
    Invoke-WebRequest -Uri $PythonUrl -OutFile $installer -UseBasicParsing
    # BESIDE, NOT INSTEAD. No PATH change, no py launcher, no file types: every
    # script on this server that runs "python" or "py" today runs exactly what
    # it ran before. SameDay always names this python.exe by its full path.
    $how = @("/quiet", "InstallAllUsers=1", "TargetDir=`"C:\Program Files\Python311`"",
             "PrependPath=0", "Include_launcher=0", "InstallLauncherAllUsers=0",
             "AssociateFiles=0", "Shortcuts=0", "Include_test=0", "Include_doc=0")
    $run = Start-Process -FilePath $installer -ArgumentList $how -Wait -PassThru
    if ($run.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Python)) {
        Stop-Here "The Python installer ended with code $($run.ExitCode)."
    }
    Yes "Installed $Python - PATH, py and file types unchanged"
}
$version = (& $Python --version) -join ""
if ($version -notmatch "^Python 3\.11\.") { Stop-Here "$Python reports '$version', not 3.11." }
Yes $version

# -- 3. The files ---------------------------------------------------------------
Head "3. Copying SameDay from K: to $Target"
# Old copies of the code (backups\) are not copied. On an update, nothing the
# server has produced is replaced: the chats (lite.db), Craft's log, the
# renders and uploads, the spend log - and never the keys.
$skipDirs = @("backups", ".venv", ".venv-gpu", "__pycache__")
$skipFiles = @("*.pyc", "PHONE_LINK.txt")
if ($Update) {
    $skipDirs += @("out", "client_files", "studio_data", "logs")
    $skipFiles += @(".env", "lite.db", "craft.db", "*.db-wal", "*.db-shm")
}
$robo = @($Source, $Target, "/E", "/R:2", "/W:5", "/NP", "/NFL", "/NDL", "/NJH") +
        @("/XD") + $skipDirs + @("/XF") + $skipFiles
& robocopy @robo | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Here "robocopy failed (exit $LASTEXITCODE)." }
Yes "Copied (robocopy exit $LASTEXITCODE)"
New-Item -ItemType Directory -Path $Logs -Force | Out-Null

# THE KEYS: copied with the folder, as the 2 November guide says, and then
# readable here by LocalSystem (the services) and Administrators only. On K:
# the check found them readable by Everyone; on this server they are not.
$keys = Join-Path $Target ".env"
if (Test-Path -LiteralPath $keys) {
    & icacls $keys /inheritance:r /grant:r "*S-1-5-18:(R)" "*S-1-5-32-544:(F)" | Out-Null
    if ($LASTEXITCODE -ne 0) { Warn "Could not narrow who can read $keys (icacls exit $LASTEXITCODE)." }
    else { Yes "Keys file in place, readable only by the services and administrators (not opened)" }
} else {
    Warn "No $keys - SameDay will start with no AI keys. Ask Muhammad (2 November guide: it comes with the folder)."
}

# -- 4. SameDay's own packages ---------------------------------------------------
Head "4. Python packages (10-20 minutes the first time)"
if (-not (Test-Path -LiteralPath (Join-Path $Venv "Scripts\python.exe"))) {
    & $Python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { Stop-Here "Could not create $Venv." }
}
$vpy = Join-Path $Venv "Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check
# CPU, because there is no GPU here: the "+cu128" builds of torch become the
# ordinary ones, and the CUDA package index is not used (the guide's own
# instruction for a machine without an NVIDIA card).
$wanted = Join-Path (Split-Path $Source -Parent) "requirements_full.txt"
if (-not (Test-Path -LiteralPath $wanted)) { Stop-Here "No requirements_full.txt beside SDI_Automation on K:." }
$cpu = Join-Path $Target "requirements_cpu.txt"
(Get-Content -LiteralPath $wanted) |
    Where-Object { $_ -notmatch '^\s*--(extra-)?index-url' } |
    ForEach-Object { $_ -replace '\+cu\d+', '' } |
    Set-Content -LiteralPath $cpu -Encoding ASCII
& $vpy -m pip install -r $cpu --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Stop-Here "pip could not install the packages (exit $LASTEXITCODE). Send Claude the lines above." }
Yes "Packages installed into $Venv"

# -- 5. The two services ---------------------------------------------------------
Head "5. Services"
foreach ($app in $Apps) {
    $name = $app.Name
    if (-not (Get-Service -Name $name -ErrorAction SilentlyContinue)) {
        Nssm @("install", $name, $vpy, "`"$(Join-Path $Target $app.Script)`"")
        Nssm @("set", $name, "DisplayName", $app.Display)
        Nssm @("set", $name, "Description", "SDI SameDay Intelligence (Muhammad Yazir). Port $($app.Port). Installed by Install-SameDay.ps1.")
        Nssm @("set", $name, "AppDirectory", $Target)
        Nssm @("set", $name, "ObjectName", "LocalSystem")
        Nssm @("set", $name, "Start", "SERVICE_AUTO_START")
        Nssm @("set", $name, "AppExit", "Default", "Restart")
        Nssm @("set", $name, "AppRestartDelay", "5000")
        Nssm @("set", $name, "AppStdout", (Join-Path $Logs "$name.log"))
        Nssm @("set", $name, "AppStderr", (Join-Path $Logs "$name.log"))
        Nssm @("set", $name, "AppRotateFiles", "1")
        Nssm @("set", $name, "AppRotateOnline", "1")
        Nssm @("set", $name, "AppRotateBytes", "10485760")
        Nssm @("set", $name, "AppEnvironmentExtra", "PYTHONUNBUFFERED=1", "PYTHONIOENCODING=utf-8")
        Yes "Created $name ($($app.Display), port $($app.Port))"
        Nssm @("start", $name)
    } else {
        Nssm @("restart", $name)
        Yes "Restarted $name on the new code"
    }
}

# -- 6. Firewall: the office and the VPN, nothing else ---------------------------
Head "6. Firewall"
foreach ($app in $Apps) {
    $rule = "SDI SameDay - port $($app.Port) from the office and VPN"
    if (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue) {
        Yes "Rule already there: $rule"
    } else {
        New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP `
            -LocalPort $app.Port -RemoteAddress $AllowFrom -Profile Any | Out-Null
        Yes "Added: $rule ($($AllowFrom -join ', '))"
    }
}

# -- 7. Is it answering? ----------------------------------------------------------
Head "7. Is it answering? (the first start loads the picture model - up to 2 minutes)"
$allUp = $true
foreach ($app in $Apps) {
    $url = "http://localhost:$($app.Port)$($app.Probe)"
    $up = $false
    $deadline = (Get-Date).AddSeconds(150)
    while ((Get-Date) -lt $deadline) {
        try {
            $answer = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
            if ($answer.StatusCode -eq 200) { $up = $true; break }
        } catch { }
        Start-Sleep -Seconds 5
    }
    if ($up) {
        Yes "$($app.Display) answers at $url"
    } else {
        $allUp = $false
        Warn "$($app.Display) did not answer at $url. The end of its log (keys removed):"
        SafeTail (Join-Path $Logs "$($app.Name).log")
    }
}
if ((Get-Service -Name "SDIIntelligence").Status -eq "Running") {
    Yes "SDI Intelligence is still running, untouched"
} else {
    Warn "SDI Intelligence is not running - this script did not touch it; check it separately."
}

# -- Verdict ----------------------------------------------------------------------
Write-Host ""
Write-Host ("=" * 72) -ForegroundColor DarkGray
if ($allUp) {
    Write-Host "  SameDay is installed. In the office or on the VPN:" -ForegroundColor Green
    Write-Host "      SameDay    http://10.0.0.5:5020" -ForegroundColor White
    Write-Host "      SDI Craft  http://10.0.0.5:5030" -ForegroundColor White
    Write-Host "  Typed briefs, files, renders, GAs and PDFs work. The microphone waits" -ForegroundColor Gray
    Write-Host "  for App Proxy (https). Past-job lookup waits for Muhammad's W: fix." -ForegroundColor Gray
} else {
    Write-Host "  Installed, but not everything answered. Send Claude everything above." -ForegroundColor Yellow
}
Write-Host ("=" * 72) -ForegroundColor DarkGray
Write-Host ""
