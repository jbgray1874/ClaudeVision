<#
.SYNOPSIS
    Run the delivery-note splitter as a Windows service on SDI-App01, checking every few
    minutes. Run ON THE SERVER, in PowerShell as Administrator.

.DESCRIPTION
    James Gray, 13 October 2026: "can we have this running on the server instead? then it's
    always up as a windows service" - after BARDON DELIVERY NOTES 7-10-2026 and ten other
    scans were never split, because the daily task on a laptop ran when the laptop happened
    to be on.

    Installs (or re-configures) the NSSM service SDISplitScan:

        python split_delivery_notes.py --source <Source> --out <Out> --watch <EveryMinutes>

    It starts with the machine, restarts if it stops, files a scan a few minutes after it
    lands, and keeps its own record of how far it has got - so there is no date to set and
    nothing to re-run by hand. Every check rewrites <Out>\_logs\service-status.txt; a check
    that split something is also in <Out>\_logs\splitscan-YYYY-MM-DD.log.

    Run it again to change anything; it re-configures the service rather than adding one.

    NO ENTRA, NO PORTS, NO APP PROXY. It is not a web service. It needs Python with pymupdf
    and Pillow, Tesseract, and an account that can read and write the share.

.PARAMETER Source
    The scanner's folder, as a UNC path. Required: there is no guessed default (see the
    splitter's own notes on the guess that built a folder tree on the share).

.PARAMETER Out
    The SplitScan folder, as a UNC path. Required.

.PARAMETER RunAsUser
    The account the service runs as. NOT LocalSystem: LocalSystem has no rights on
    \\sdi-dc01\shareddata$, so it would start, report itself running, and file nothing -
    which is exactly what the first NSSM service on 8071 did. Use an account that can open
    the Scans folder in Explorer. You are prompted for its password; it is handed to the
    service manager and kept nowhere else. When that password changes, run this again.

.PARAMETER EveryMinutes
    How often it looks. Defaults to 5.

.EXAMPLE
    .\Install-SplitScanService.ps1 -Source '\\sdi-dc01\shareddata$\Shared\Logistics\Scans' `
                                   -Out    '\\sdi-dc01\shareddata$\Shared\Logistics\Scans\SplitScan'

.EXAMPLE
    .\Install-SplitScanService.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$Source = '',
    [string]$Out = '',
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME",
    [int]$EveryMinutes = 5,
    [string]$Python = '',
    [string]$NssmExe = '',
    [string]$ServiceName = 'SDISplitScan',
    [string]$LogDir = 'C:\ClaudeVision\output\logs',
    [switch]$Remove
)

# Native commands (nssm) write to stderr; under "Stop" Windows PowerShell 5.1 turns that into
# a terminating error. Exit codes are checked by hand.
$ErrorActionPreference = 'Continue'

function Stop-Install([string]$Text) {
    Write-Host ''
    Write-Host "  STOPPED: $Text" -ForegroundColor Red
    Write-Host ''
    exit 1
}
function Say([string]$Text, [string]$Colour = 'Gray') { Write-Host "  $Text" -ForegroundColor $Colour }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
         ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Stop-Install 'Run this in PowerShell as Administrator (it installs a service).' }

# $PSScriptRoot is empty inside param() under `powershell -File`; asked here instead.
$here = $PSScriptRoot
if (-not $here -and $MyInvocation.MyCommand.Path) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
$script = Join-Path $here 'split_delivery_notes.py'
if (-not (Test-Path $script)) { Stop-Install "Cannot find $script. Deploy first (Deploy-AMCRM.ps1 copies it here)." }

# -- NSSM ---------------------------------------------------------------------------------
if (-not $NssmExe) {
    $cmd = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($cmd) { $NssmExe = $cmd.Source }
}
if (-not $NssmExe) {
    foreach ($cand in @('C:\Tools\nssm.exe', 'C:\tools\nssm-2.24\win64\nssm.exe',
                        'C:\tools\nssm\win64\nssm.exe', 'C:\nssm\win64\nssm.exe')) {
        if (Test-Path $cand) { $NssmExe = $cand; break }
    }
}
if (-not $NssmExe) { Stop-Install 'nssm.exe not found. Pass -NssmExe <path> (the other services here use C:\Tools\nssm.exe).' }

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

if ($Remove) {
    if (-not $existing) { Say "There is no $ServiceName service. Nothing to remove." Green; exit 0 }
    & $NssmExe stop $ServiceName | Out-Null
    & $NssmExe remove $ServiceName confirm | Out-Null
    Say "$ServiceName removed." Green
    exit 0
}

# -- THE FOLDERS --------------------------------------------------------------------------
foreach ($pair in @(@('-Source', $Source), @('-Out', $Out))) {
    if (-not $pair[1]) { Stop-Install "$($pair[0]) is required, as a UNC path (\\server\share\...)." }
    if ($pair[1] -match '^[A-Za-z]:') {
        Stop-Install "$($pair[0]) is a drive letter. A service has no mapped drives; give the UNC path (\\server\share\...)."
    }
}
if (-not (Test-Path -LiteralPath $Source)) {
    Stop-Install "$Source cannot be reached from this session. Check the path (it is the folder the scanner writes into)."
}
if (-not (Test-Path -LiteralPath $Out)) {
    Stop-Install "$Out cannot be reached from this session. It should already exist - the laptop's runs made it."
}

# -- PYTHON, AND WHAT THE SPLITTER NEEDS ----------------------------------------------------
if (-not $Python) {
    foreach ($cand in @('C:\ClaudeVision\sdi-intelligence-backend\.venv\Scripts\python.exe',
                        'C:\ClaudeVision\.venv\Scripts\python.exe')) {
        if (Test-Path $cand) { $Python = $cand; break }
    }
}
if (-not $Python) {
    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike '*WindowsApps*') { $Python = $cmd.Source }
}
if (-not $Python -or -not (Test-Path $Python)) { Stop-Install 'No Python found. Pass -Python <full path to python.exe>.' }
& $Python -c "import pymupdf, PIL" 2>$null
if ($LASTEXITCODE -ne 0) {
    Stop-Install ("Python is missing the PDF and image packages. Install them, then run this again:`n`n" +
                  "      & '$Python' -m pip install pymupdf pillow`n")
}

# Tesseract: PATH, then where the installer puts it (it does not add itself to PATH).
$tess = (Get-Command tesseract -ErrorAction SilentlyContinue).Source
if (-not $tess) {
    foreach ($cand in @("$env:ProgramFiles\Tesseract-OCR\tesseract.exe",
                        "${env:ProgramFiles(x86)}\Tesseract-OCR\tesseract.exe")) {
        if (Test-Path $cand) { $tess = $cand; break }
    }
}
if (-not $tess) {
    Stop-Install @'
Tesseract (the OCR) is not installed on this server. The scans have no text layer, so nothing
can be read without it. Install it for all users, then run this again:
      winget install UB-Mannheim.TesseractOCR
  or, where winget is not available, the Windows installer from
      https://github.com/UB-Mannheim/tesseract/wiki
'@
}

# -- THE ACCOUNT ----------------------------------------------------------------------------
if ($RunAsUser -notmatch '\\' -and $RunAsUser -notmatch '@') { $RunAsUser = "$env:USERDOMAIN\$RunAsUser" }
$secure = Read-Host -AsSecureString "Password for $RunAsUser (the service runs as this account to reach the share)"
$plain = (New-Object System.Management.Automation.PSCredential($RunAsUser, $secure)).GetNetworkCredential().Password
if (-not $plain) { Stop-Install 'No password given.' }

Write-Host ''
Write-Host "SPLITSCAN SERVICE  ->  $ServiceName" -ForegroundColor Cyan
Write-Host ('-' * 64)
Say "python    : $Python"
Say "tesseract : $tess"
Say "source    : $Source"
Say "out       : $Out"
Say "checks    : every $EveryMinutes minute(s), as $RunAsUser"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

# -- INSTALL OR RE-CONFIGURE ----------------------------------------------------------------
if ($existing) {
    Say "Re-configuring the existing $ServiceName service..."
    & $NssmExe stop $ServiceName 2>&1 | Out-Null
} else {
    & $NssmExe install $ServiceName $Python 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Stop-Install "nssm could not install $ServiceName (exit $LASTEXITCODE)." }
}
$params = '"{0}" --source "{1}" --out "{2}" --watch {3}' -f $script, $Source, $Out, $EveryMinutes
$settings = @(
    @('Application', $Python),
    @('AppParameters', $params),
    @('AppDirectory', $here),
    @('DisplayName', 'SDI SplitScan (delivery note splitter)'),
    @('Description', 'Splits scanned delivery notes into one PDF per note in SplitScan. Checks every few minutes.'),
    @('Start', 'SERVICE_DELAYED_AUTO_START'),
    @('AppExit', 'Default', 'Restart'),
    @('AppRestartDelay', '60000'),
    @('AppStdout', (Join-Path $LogDir 'splitscan_service.log')),
    @('AppStderr', (Join-Path $LogDir 'splitscan_service_error.log')),
    @('AppRotateFiles', '1'),
    @('AppRotateOnline', '1'),
    @('AppRotateBytes', '1048576'),
    @('AppEnvironmentExtra', "SDI_TESSERACT_PATH=$tess", 'PYTHONUNBUFFERED=1', 'PYTHONIOENCODING=utf-8')
)
foreach ($s in $settings) {
    & $NssmExe set $ServiceName @s 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Stop-Install "nssm could not set $($s[0]) (exit $LASTEXITCODE)." }
}
# NSSM grants the account "Log on as a service" when it sets it.
& $NssmExe set $ServiceName ObjectName $RunAsUser $plain 2>&1 | Out-Null
$plain = $null
if ($LASTEXITCODE -ne 0) {
    Stop-Install "nssm could not set the service account to $RunAsUser (exit $LASTEXITCODE). Check the name (DOMAIN\user) and password."
}

# -- START IT, AND PROVE IT REACHED THE SHARE -------------------------------------------------
# "Running" only says the process is up. The status file is written by the splitter, ON THE
# SHARE, as the service account - so a fresh one proves the account, the path and the code.
$status = Join-Path $Out '_logs\service-status.txt'
$began = Get-Date
& $NssmExe start $ServiceName 2>&1 | Out-Null
Say 'Started. Waiting for its first check to reach the share (up to 2 minutes)...'
$deadline = $began.AddSeconds(120)
$ok = $false
do {
    Start-Sleep -Seconds 5
    if ((Test-Path -LiteralPath $status) -and (Get-Item -LiteralPath $status).LastWriteTime -ge $began.AddSeconds(-5)) { $ok = $true }
} until ($ok -or (Get-Date) -gt $deadline)

Write-Host ''
if ($ok) {
    Say "$ServiceName is running and has checked the scan folder:" Green
    Get-Content -LiteralPath $status | ForEach-Object { Say "    $_" White }
    Write-Host ''
    Say 'Its first check also files anything the old daily task missed, so it may still be'
    Say "reading for a while. Follow it in $Out\_logs\splitscan-$(Get-Date -Format yyyy-MM-dd).log"
    Write-Host ''
    Say 'Last step, on the LAPTOP, so the old task stops competing for the folder:' Yellow
    Write-Host "      Disable-ScheduledTask -TaskName 'SDI Split Delivery Note Scans'" -ForegroundColor White
    Write-Host ''
    exit 0
}
$state = (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue).Status
Say "$ServiceName did not write $status within 2 minutes (service state: $state)." Red
Say 'Usual causes: the account cannot open the share, the password is wrong, or the account'
Say 'lacks "Log on as a service". What the service said:'
foreach ($f in @('splitscan_service_error.log', 'splitscan_service.log')) {
    $p = Join-Path $LogDir $f
    if (Test-Path $p) {
        Say "--- $p" White
        Get-Content -LiteralPath $p -Tail 15 | ForEach-Object { Say "    $_" }
    }
}
exit 1
