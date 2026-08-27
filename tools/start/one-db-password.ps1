<#
    Make the two .env files stop disagreeing about the SQL password, and prove it.

        .\tools\start\one-db-password.ps1              # look, change nothing
        .\tools\start\one-db-password.ps1 -Apply       # fix it, restart, verify

    WHAT THIS IS FOR, in one sentence: BACKEND DEGRADED with "Login failed for user 'AIBot'"
    while the engine connects perfectly well on the same machine.

    WHY THAT HAPPENS. There are two files called .env and they are read in OPPOSITE orders:

        engine   src\config.py    repo-root .env, then src\.env  - RETURNS on the first hit
        backend  config.py        its OWN .env FIRST, then the repo root,
                                  python-dotenv override=False, so the FIRST file wins

    So a password rotated in the repo-root .env is picked up by the engine and SHADOWED for the
    service by whatever is sitting beside it. Both processes are behaving correctly. One of them
    is using last month's password.

    THE FIX IS NOT TO COPY THE VALUE ACROSS. Two copies of a secret is what caused this, and
    copying it again just resets the clock until the next rotation. Because the backend reads
    the repo-root .env as its SECOND layer, deleting the duplicate from the service's own .env
    makes it fall through to the shared one - so there is ONE place to rotate, permanently.

    So this comments the line out rather than deleting it, dated, with the reason, and leaves a
    timestamped backup beside the file. Nothing is printed but LENGTHS: this writes to a
    terminal that gets screenshotted.

    IT ALSO RESTARTS AND RE-CHECKS, because .env is read once at process start - an edited file
    with no restart looks exactly like an edit that did not work, which is its own afternoon.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [int]$Port = 8072,
    [string]$Key = "SDI_DB_PASSWORD"
)

$ErrorActionPreference = "Stop"
$root    = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$rootEnv = Join-Path $root ".env"
$beEnv   = Join-Path $root "sdi-intelligence-backend\.env"

function Get-EnvValue([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $t = $line.Trim()
        if ($t.StartsWith("#") -or -not $t.Contains("=")) { continue }
        $k, $v = $t.Split("=", 2)
        if ($k.Trim() -eq $Name) { return $v.Trim().Trim('"').Trim("'") }
    }
    return $null
}

Write-Host ""
Write-Host "ONE PASSWORD, TWO FILES  -  $Key" -ForegroundColor Cyan
Write-Host ("-" * 62)

foreach ($f in @($rootEnv, $beEnv)) {
    if (-not (Test-Path -LiteralPath $f)) {
        Write-Host ("  MISSING  {0}" -f $f) -ForegroundColor Yellow
    }
}

$rootVal = Get-EnvValue $rootEnv $Key
$beVal   = Get-EnvValue $beEnv   $Key
$show    = { param($v) if ($null -eq $v) { "not set" } elseif ($v -eq "") { "set but EMPTY" } else { "$($v.Length) chars" } }

Write-Host ("  repo-root .env                      {0}" -f (& $show $rootVal))
Write-Host ("  sdi-intelligence-backend\.env       {0}" -f (& $show $beVal))
Write-Host ""

if ($null -eq $beVal) {
    Write-Host "  Nothing to do - the service has no duplicate; it already falls through to" -ForegroundColor Green
    Write-Host "  the repo-root .env, which is the arrangement this script exists to create." -ForegroundColor Green
    Write-Host ""
    return
}
if ($null -eq $rootVal -or $rootVal -eq "") {
    Write-Host "  STOP. The repo-root .env does not set $Key." -ForegroundColor Red
    Write-Host "  Removing the service's copy would leave it with no password at all. Put the" -ForegroundColor Red
    Write-Host "  current one in the repo-root .env FIRST, then run this again." -ForegroundColor Red
    Write-Host ""
    exit 2
}
if ($rootVal -eq $beVal) {
    Write-Host "  The two agree today, so nothing is broken right now - but they are still two" -ForegroundColor Yellow
    Write-Host "  copies, and the next rotation will break exactly one of them again." -ForegroundColor Yellow
} else {
    Write-Host "  THEY DISAGREE. The service is using its own copy and ignoring the shared one." -ForegroundColor Red
    Write-Host "  That is the BACKEND DEGRADED / 'Login failed' you are looking at." -ForegroundColor Red
}
Write-Host ""

if (-not $Apply) {
    Write-Host "  Re-run with -Apply to comment out the service's copy, restart, and verify."
    Write-Host ""
    return
}

# ── change it ──────────────────────────────────────────────────────────────────
$stamp  = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = "$beEnv.$stamp.bak"
Copy-Item -LiteralPath $beEnv -Destination $backup
Write-Host "  backup   $backup"

$out = New-Object System.Collections.Generic.List[string]
$done = $false
foreach ($line in Get-Content -LiteralPath $beEnv -Encoding UTF8) {
    $t = $line.Trim()
    if (-not $done -and -not $t.StartsWith("#") -and $t.Contains("=") -and
        $t.Split("=", 2)[0].Trim() -eq $Key) {
        $out.Add("# $Key removed $(Get-Date -Format 'yyyy-MM-dd') - it SHADOWED the repo-root")
        $out.Add("# .env for this service and left it on an old password while the engine used")
        $out.Add("# the current one. One copy only: rotate it in the repo-root .env.")
        $out.Add("# $line")
        $done = $true
        continue
    }
    $out.Add($line)
}
# NO BOM. Set-Content -Encoding UTF8 emits one on Windows PowerShell 5.1, and python-dotenv
# would then read the file's FIRST key as "\ufeffSDI_..." — breaking a setting at random in
# the very file we are editing to fix a configuration fault. WriteAllLines defaults to no BOM.
[System.IO.File]::WriteAllLines($beEnv, $out)
Write-Host "  edited   $beEnv  ($Key commented out)" -ForegroundColor Green

# ── restart, because .env is read once at start ───────────────────────────────
$restart = Join-Path $PSScriptRoot "restart-service.ps1"
if (Test-Path -LiteralPath $restart) {
    Write-Host ""
    Write-Host "  restarting the service so the change is actually read..."
    & $restart -Port $Port
} else {
    Write-Host "  restart-service.ps1 not found - restart the service yourself before checking." -ForegroundColor Yellow
    return
}

# ── prove it ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  asking the service what it thinks now..."
try {
    $h = Invoke-RestMethod "http://localhost:$Port/api/health" -TimeoutSec 20
    $colour = if ($h.status -eq "ok") { "Green" } else { "Red" }
    Write-Host ("  status   {0}" -f $h.status) -ForegroundColor $colour
    Write-Host ("  database {0}" -f $h.database.status)
    if ($h.database.status -ne "ok") {
        Write-Host ("  detail   {0}" -f $h.database.detail) -ForegroundColor Yellow
        if ($h.database.note) { Write-Host ("  note     {0}" -f $h.database.note) -ForegroundColor Yellow }
        Write-Host ""
        Write-Host "  Still failing. The repo-root .env's password is the one in use now, so" -ForegroundColor Yellow
        Write-Host "  either it is not the current one, or the login itself needs attention." -ForegroundColor Yellow
        Write-Host "  The backup above restores the previous state exactly." -ForegroundColor Yellow
    }
    foreach ($k in "staging", "workbook_template") {
        if ($h.$k -and -not $h.$k.reachable) {
            Write-Host ("  {0,-8} NOT REACHABLE - {1}" -f $k, $h.$k.path) -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "  could not reach http://localhost:$Port/api/health - is the service up?" -ForegroundColor Yellow
}
Write-Host ""
