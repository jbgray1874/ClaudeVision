<#
    Can this machine run estimates? (D-706, SCRUM-183 / SCRUM-184)

        .\tools\start\check-runner-host.ps1

    Prints, for this machine:

        machine      name, Windows version, domain role, cores, memory, free disk
        excel        installed or not, and its version (estimates need it)
        solidworks   registered or not (reads models directly)
        docmgr       the SOLIDWORKS Document Manager registered or not (the backup reader)
        python       the engine checkout and its virtualenv, and whether pywin32 loads
        shares       the estimating share, the AI template and Live Enquiry by UNC path
        odbc         which SQL Server ODBC drivers are installed
        portal       whether the estimating portal answers on its port
        settings     the NAMES of the relevant settings in the .env files and this
                     machine's environment, each marked set or empty. Never a value.

    Runs anywhere: a machine with no engine checkout is checked too, and simply reports
    the checkout as missing. Paste it on a server that has no git.

    READ-ONLY. It installs, starts, stops and writes nothing.

    ASCII ONLY. See start-service.ps1 for why.
#>
param(
    [string]$EngineRoot = "C:\ClaudeVision",
    [string]$Share = "\\sdi-dc01\shareddata$\Shared\Estimating"
)

function Say([string]$what, [string]$text) { "{0,-11} {1}" -f $what, $text }
function KeyExists([string]$path) { try { return [bool](Test-Path -LiteralPath $path) } catch { return $false } }

"=== Can this machine run estimates? ==="

# -- machine ---------------------------------------------------------------------------
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $cs = Get-CimInstance Win32_ComputerSystem
    $roles = @{0="standalone workstation";1="domain workstation";2="standalone server";
               3="member server";4="BACKUP DOMAIN CONTROLLER";5="PRIMARY DOMAIN CONTROLLER"}
    $role = $roles[[int]$cs.DomainRole]
    $cores = (Get-CimInstance Win32_Processor | Measure-Object NumberOfLogicalProcessors -Sum).Sum
    $ramGb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
    $freeGb = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
    Say "machine" ("{0}, {1} (build {2}), {3}" -f $env:COMPUTERNAME, $os.Caption, $os.BuildNumber, $role)
    Say "" ("{0} logical cores, {1} GB memory, {2} GB free on C:" -f $cores, $ramGb, $freeGb)
    if ([int]$cs.DomainRole -ge 4) {
        Say "" "STOP: this is a domain controller. Do not install Office or run estimates on it."
    }
} catch { Say "machine" "could not be read: $($_.Exception.Message)" }

# -- excel -----------------------------------------------------------------------------
$excelPath = $null
foreach ($k in @("HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe",
                 "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\excel.exe")) {
    if (KeyExists $k) { try { $excelPath = (Get-ItemProperty -LiteralPath $k).'(default)' } catch {} }
    if ($excelPath) { break }
}
$excelCom = KeyExists "Registry::HKEY_CLASSES_ROOT\Excel.Application\CLSID"
if ($excelPath -and (Test-Path -LiteralPath $excelPath)) {
    $ver = ""
    try { $ver = (Get-Item -LiteralPath $excelPath).VersionInfo.ProductVersion } catch {}
    Say "excel" ("installed, version {0}, COM registered: {1}" -f $ver, $excelCom)
} elseif ($excelCom) {
    Say "excel" "COM class registered but excel.exe not found on its usual path"
} else {
    Say "excel" "NOT installed. Estimates need a licensed desktop Excel on this machine."
}
try {
    $c2r = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration" -ErrorAction Stop
    Say "" ("Office products: {0}" -f $c2r.ProductReleaseIds)
} catch {}

# -- solidworks and the document manager --------------------------------------------------
if (KeyExists "Registry::HKEY_CLASSES_ROOT\SldWorks.Application") {
    Say "solidworks" "registered (the main model reader can run here)"
} else {
    Say "solidworks" "not registered (models need the Document Manager backup, or a fresh extract)"
}
if (KeyExists "Registry::HKEY_CLASSES_ROOT\SwDocumentMgr.SwDMClassFactory") {
    Say "docmgr" "SOLIDWORKS Document Manager registered"
} else {
    Say "docmgr" "SOLIDWORKS Document Manager NOT registered (the backup reader cannot run here)"
}

# -- python and the engine checkout ---------------------------------------------------------
$venvPy = Join-Path $EngineRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $EngineRoot) {
    Say "python" ("engine checkout: {0}" -f $EngineRoot)
    if (Test-Path -LiteralPath $venvPy) {
        $pv = (& $venvPy --version 2>&1) -join " "
        $pw = (& $venvPy -c "import win32com.client; print('pywin32 loads')" 2>&1) -join " "
        Say "" ("virtualenv: {0}; {1}" -f $pv, $pw)
    } else {
        Say "" "NO virtualenv at .venv\Scripts\python.exe"
    }
} else {
    Say "python" ("no engine checkout at {0}" -f $EngineRoot)
}
$sysPy = Get-Command python -ErrorAction SilentlyContinue
if ($sysPy) { Say "" ("python on PATH: {0}" -f $sysPy.Source) } else { Say "" "no python on PATH" }
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) { Say "" "git: installed" } else { Say "" "git: not installed (use push-to-server.ps1 from the laptop)" }

# -- shares ---------------------------------------------------------------------------------
$tpl = Join-Path $Share "Completed\AI Estimating\AISheets\Blank Estimate Sheet  WB 2026.xlsx"
$live = Join-Path $Share "Completed\AI Estimating\Live Enquiry"
foreach ($p in @($Share, $tpl, $live)) {
    $ok = $false
    try { $ok = Test-Path -LiteralPath $p } catch {}
    Say "shares" ("{0}  {1}" -f $(if ($ok) { "reachable" } else { "NOT reachable" }), $p)
}

# -- odbc -------------------------------------------------------------------------------------
try {
    $drv = Get-OdbcDriver -Platform 64-bit -ErrorAction Stop | Where-Object { $_.Name -like "*SQL Server*" } |
        Select-Object -ExpandProperty Name
    Say "odbc" $(if ($drv) { ($drv -join "; ") } else { "no SQL Server ODBC driver" })
} catch { Say "odbc" "could not be listed" }

# -- settings: names only, never values ------------------------------------------------------
$pattern = 'DOCMGR|DOC_MGR|_DM_|^DM_|SWDM|SW_DM|SOLIDWORKS|_SW_|LICEN|^SDI_SERVER$|^SDI_API_KEY$|^SDI_MAX_CONCURRENT_RUNS$|^XAI_API_KEY$|^SDI_WB_TEMPLATE$'
$envFiles = @((Join-Path $EngineRoot ".env"), (Join-Path $EngineRoot "src\.env"),
              (Join-Path $EngineRoot "sdi-intelligence-backend\.env"))
$found = 0
foreach ($f in $envFiles) {
    if (-not (Test-Path -LiteralPath $f)) { continue }
    foreach ($line in (Get-Content -LiteralPath $f -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $name = $Matches[1]; $val = $Matches[2].Trim().Trim('"').Trim("'")
            if ($name -match $pattern) {
                Say "settings" ("{0,-34} {1,-6} in {2}" -f $name, $(if ($val) { "set" } else { "EMPTY" }), $f)
                $found++
            }
        }
    }
}
foreach ($scope in @("Machine", "User")) {
    $vars = [Environment]::GetEnvironmentVariables($scope)
    foreach ($name in $vars.Keys) {
        if ($name -match $pattern) {
            Say "settings" ("{0,-34} {1,-6} in the {2} environment" -f $name, $(if ($vars[$name]) { "set" } else { "EMPTY" }), $scope.ToLower())
            $found++
        }
    }
}
if (-not $found) { Say "settings" "none of the relevant names is set on this machine" }

# -- portal --------------------------------------------------------------------------------------
$server = "http://10.0.0.5:8071"
$rootEnv = Join-Path $EngineRoot ".env"
if (Test-Path -LiteralPath $rootEnv) {
    $m = Select-String -LiteralPath $rootEnv -Pattern '^\s*SDI_SERVER\s*=\s*(.+)$' | Select-Object -First 1
    if ($m) { $server = $m.Matches[0].Groups[1].Value.Trim().Trim('"') }
}
try {
    $u = [Uri]$server
    $t = Test-NetConnection -ComputerName $u.Host -Port $u.Port -WarningAction SilentlyContinue
    Say "portal" ("{0}  {1}" -f $(if ($t.TcpTestSucceeded) { "answers" } else { "does NOT answer" }), $server)
} catch { Say "portal" ("could not test {0}" -f $server) }

"=== end. Nothing on this machine was changed. ==="
