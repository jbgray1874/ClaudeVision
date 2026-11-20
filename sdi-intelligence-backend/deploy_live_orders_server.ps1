<#
  deploy_live_orders_server.ps1 - puts Live Orders and Estimate -> X3 on the SDI Intelligence portal running on THIS
  machine (the server, SDI-APP01). Written 20 Nov 2026 (Estimate -> X3 added the same evening).

  Run ON the server, in PowerShell as administrator:
      powershell -ExecutionPolicy Bypass -File C:\SDI_X3\repo\sdi-intelligence-backend\deploy_live_orders_server.ps1

  Before running it (from James's PC - see the runbook, 20 Nov "server"):
    - the repo copied to C:\SDI_X3\repo on the server
    - the X3 settings file copied to C:\ProgramData\SDI\x3_api.json on the server (never by email, chat or git)

  What it does, stopping at the first problem:
    1. finds the running portal (whatever listens on port 8071): its folder, its Python, and its Windows service
    2. checks that Python is 3.10+ and has openpyxl and xlrd (installs them for every account if missing)
    3. locks the X3 settings file down (Administrators, SYSTEM and the service's account only)
    4. makes the working folders C:\ProgramData\SDI\LiveOrders (runs, X3 exports) and C:\ProgramData\SDI\Estimating
    5. previews add_live_orders_to_portal.py, ASKS, then applies it (it backs every file up first)
    6. restarts the portal's service and checks that Live Orders answers
    7. checks that the service's account can write to the LiveOrders and SageEstimates folders (as SYSTEM, one-off task)
  Read-only towards Sage X3. Changes only the portal folder (with backups) and C:\ProgramData\SDI.
#>
param(
    [int]$Port = 8071,
    [string]$Target = "",                                   # the portal folder (app.py); found automatically if blank
    [string]$X3Config = "C:\ProgramData\SDI\x3_api.json",
    [string]$Data = "C:\ProgramData\SDI\LiveOrders",
    [string]$EstRuns = "C:\ProgramData\SDI\Estimating",
    [string]$Share = "\\sdi-dc01\shareddata$\Shared\Operations\Reporting\LiveOrders",
    [string]$EstShare = "\\sdi-dc01\shareddata$\Shared\Operations\Reporting\SageEstimates"
)
$ErrorActionPreference = "Continue"
$Installer = Join-Path $PSScriptRoot "add_live_orders_to_portal.py"
function Say([string]$m, [string]$c = "Gray") { Write-Host $m -ForegroundColor $c }
function Fail([string]$m) { Say "STOPPED: $m" Red; exit 1 }

Say "== Live Orders -> SDI Intelligence portal on $env:COMPUTERNAME ==" Yellow
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) { Fail "run PowerShell as administrator" }
if (-not (Test-Path $Installer)) { Fail "can't find $Installer - is the repo copied to C:\SDI_X3\repo?" }

# 1. the running portal ------------------------------------------------------------------------------------------
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $conn) { Fail "nothing is listening on port $Port - start the portal first" }
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($conn.OwningProcess)"
$py = $proc.ExecutablePath
if (-not $Target) {
    $tokens = [regex]::Matches([string]$proc.CommandLine, '"[^"]+"|\S+') | ForEach-Object { $_.Value.Trim('"') }
    $app = $tokens | Where-Object { $_ -match '\\app\.py$' } | Select-Object -First 1
    if (-not $app) { Fail "can't see app.py in '$($proc.CommandLine)' - run again with -Target <portal folder>" }
    $Target = Split-Path -Parent $app
}
if (-not (Test-Path (Join-Path $Target "app.py"))) { Fail "no app.py in $Target" }
$svc = Get-CimInstance Win32_Service | Where-Object { $_.ProcessId -eq $proc.ProcessId -or $_.ProcessId -eq $proc.ParentProcessId } |
       Select-Object -First 1
Say "Portal folder : $Target"
Say "Python        : $py"
if ($svc) { Say "Service       : $($svc.Name), runs as $($svc.StartName)" }
else      { Say "Service       : none - the portal was started by hand (it stops when that session ends)" DarkYellow }

# 2. Python ------------------------------------------------------------------------------------------------------
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { Fail "$py is older than Python 3.10" }
foreach ($mod in @("openpyxl", "xlrd")) {          # workbooks; old .xls estimates
    & $py -s -c "import $mod" 2>$null                 # -s: as the service sees it (not this user's own folder)
    if ($LASTEXITCODE -ne 0) {
        Say "Installing $mod into $py for every account ..."
        & $py -s -m pip install $mod
        if ($LASTEXITCODE -ne 0) { Fail "couldn't install $mod - run:  `"$py`" -s -m pip install $mod" }
    }
}
Say "Python OK (3.10+, openpyxl, xlrd)" Green

# 3. the X3 settings file ----------------------------------------------------------------------------------------
if (-not (Test-Path $X3Config)) { Fail "the X3 settings file isn't at $X3Config - copy it from your PC first (see the runbook)" }
$acct = if ($svc) { [string]$svc.StartName } else { "" }
$grants = @("*S-1-5-32-544:F", "*S-1-5-18:F")                # Administrators, SYSTEM (by SID: any Windows language)
if ($acct -and $acct -notmatch '^(LocalSystem|NT AUTHORITY\\SYSTEM)$') { $grants += "${acct}:R" }
& icacls $X3Config /inheritance:r /grant:r $grants | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "couldn't restrict $X3Config" }
Say "X3 settings file locked down: Administrators, SYSTEM$(if ($grants.Count -gt 2) { ", $acct" })" Green

# 4. working folder ----------------------------------------------------------------------------------------------
New-Item -ItemType Directory -Force -Path "$Data\runs", "$Data\X3_exports", $EstRuns | Out-Null
if ($acct -and $acct -notmatch '^(LocalSystem|NT AUTHORITY\\SYSTEM)$') {
    & icacls $Data /grant "${acct}:(OI)(CI)M" | Out-Null
    & icacls $EstRuns /grant "${acct}:(OI)(CI)M" | Out-Null
}
Say "Working folders: $Data, $EstRuns" Green

# 5. the installer: preview, ask, apply --------------------------------------------------------------------------
$args5 = @($Installer, "--target", $Target, "--x3-config", $X3Config, "--runs", "$Data\runs",
           "--exports", "$Data\X3_exports", "--share", $Share, "--est-runs", $EstRuns, "--est-share", $EstShare)
Say "`n-- preview --" Yellow
& $py @args5
if ($LASTEXITCODE -ne 0) { Fail "the installer stopped (above) - nothing was changed" }
$ans = Read-Host "`nApply these changes? (Y/N)"
if ($ans -notmatch '^[Yy]') { Say "Nothing changed."; exit 0 }
& $py @args5 --apply
if ($LASTEXITCODE -ne 0) { Fail "the installer failed (above)" }

# 6. restart and check -------------------------------------------------------------------------------------------
if ($svc) {
    Say "`nRestarting $($svc.Name) ..."
    Restart-Service -Name $svc.Name -Force
    $ok = $false
    for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
        Start-Sleep -Seconds 2
        try {
            $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://localhost:$Port/api/live-orders/dashboard"
            $ok = ($r.StatusCode -eq 200 -and $r.Content -match "Live Orders")
        } catch { }
    }
    $now = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $started = if ($now) { (Get-Process -Id $now.OwningProcess).StartTime } else { $null }
    if ($ok) { Say "Live Orders answers on http://localhost:$Port (portal started $started)" Green }
    else { Fail "Live Orders doesn't answer after the restart (portal started $started). Check that only the service holds port $Port." }
} else {
    Say "`nNot a service: stop the hand-started portal and start it again so app.py is re-read." DarkYellow
}

# 7. can the service's account write to Production's folder? -----------------------------------------------------
if ($acct -match '^(LocalSystem|NT AUTHORITY\\SYSTEM)$') {
    foreach ($dir in @($Share, $EstShare)) {
        Say "`nChecking SYSTEM (the computer account $env:COMPUTERNAME`$) can write to $dir ..."
        $inner = "try { New-Item -ItemType Directory -Force -Path '$dir' | Out-Null; " +
                 "Set-Content -Path '$dir\_sdi_write_test.tmp' -Value ok; Remove-Item -Path '$dir\_sdi_write_test.tmp'; exit 0 } " +
                 "catch { exit 1 }"
        $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($inner))
        $task = "SDI_LiveOrders_write_test"
        $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -EncodedCommand $enc"
        Register-ScheduledTask -TaskName $task -Action $action -User "SYSTEM" -RunLevel Highest -Force | Out-Null
        Start-ScheduledTask -TaskName $task
        for ($i = 0; $i -lt 30; $i++) {
            Start-Sleep -Seconds 1
            if ((Get-ScheduledTask -TaskName $task).State -ne "Running") { break }
        }
        $res = (Get-ScheduledTaskInfo -TaskName $task).LastTaskResult
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        if ($res -eq 0) { Say "Write test OK: $dir" Green }
        else { Say ("Write test FAILED (code $res) on $dir : give the computer account $env:COMPUTERNAME`$ Modify on it " +
                    "(share and folder), or run the service as a domain account that has it.") Red }
    }
} elseif ($acct) {
    Say "`nThe service runs as $acct - make sure that account can write to $Share and $EstShare." DarkYellow
}

Say ("`nDone. Open http://$($env:COMPUTERNAME):$Port (or http://10.0.0.5:$Port): Live Orders -> Regenerate first (it also " +
     "pulls the X3 product list that Estimate -> X3 checks against), then Estimate -> X3.") Yellow
