<#
    THE WHOLE DEPLOY, IN ONE COMMAND.  RUN ON THE LAPTOP, VPN connected:

        cd C:\ClaudeVision
        .\sdi-intelligence-backend\deploy\Ship-It.ps1

    Pull, deploy, restart, prove it took. Stops at the first thing that goes
    wrong and says what to do about it.

    WHY THIS EXISTS
    Shipping a change was four commands in three different places, and two of
    them I got wrong from memory - a port that was not the port, and
    Restart-Service -ComputerName, which does not exist in Windows PowerShell
    5.1. Every one of them was also a round trip to ask which machine it
    belonged to. They all belong here, on the laptop, so they are all here.

        -Check     show what would change and stop. Copies nothing.
        -NoPull    deploy what is already checked out.
        -NoRestart deploy without restarting (you will be told it matters).
#>
[CmdletBinding()]
param(
    [switch]$Check,
    [switch]$NoPull,
    [switch]$NoRestart,
    [string]$Server = "10.0.0.5",
    # The remote the fix is pushed to. NOT 'origin' on this laptop, which is a
    # different repository (jbgraysdi2026) - an hour went on that on 29 October.
    [string]$Remote = "jbg",
    [string]$Branch = "claude/app-portal-main-2026"
)

$ErrorActionPreference = "Continue"
$here = $PSScriptRoot
$repo = Split-Path -Parent (Split-Path -Parent $here)

function Step([string]$Text) {
    Write-Host ""
    Write-Host "== $Text" -ForegroundColor Cyan
}
function Die([string]$Text) {
    Write-Host ""
    Write-Host "  STOPPED: $Text" -ForegroundColor Red
    Write-Host ""
    exit 1
}

Write-Host ""
Write-Host "SHIP IT  ->  $Server" -ForegroundColor Cyan
Write-Host ("=" * 68)

# -- 1. Latest code ------------------------------------------------------------
if (-not $NoPull) {
    Step "1. Getting the latest code ($Remote/$Branch)"
    Push-Location $repo
    $out = & git pull $Remote $Branch 2>&1
    $ok = ($LASTEXITCODE -eq 0)
    $commit = ((& git rev-parse --short HEAD 2>&1) -join "").Trim()
    Pop-Location
    $out | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
    if (-not $ok) {
        Die ("git pull failed, so nothing was deployed. If it is a merge conflict, " +
             "sort it and run this again; nothing has been copied.")
    }
    Write-Host "  Now at $commit" -ForegroundColor Green
} else {
    Step "1. Skipping the pull (-NoPull)"
}

# -- 2. Deploy -----------------------------------------------------------------
Step "2. Deploying"
$deploy = Join-Path $here "Deploy-AMCRM.ps1"
if (-not (Test-Path -LiteralPath $deploy)) { Die "Deploy-AMCRM.ps1 is missing from $here" }
if ($Check) {
    & $deploy -Check -Server $Server -Remote $Remote
    Write-Host ""
    Write-Host "  Check only - nothing was copied. Run again without -Check to deploy." -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

# -- THE OTHER DEPLOY, WHEN THE CHANGE IS NOT ON THIS ONE'S LIST ---------------
#
# Deploy-AMCRM copies a named list. push-to-server.ps1 copies the whole backend
# folder and is the only way app.py, the estimating API and the rest reach the
# server - and it does NOT pull, so running it by hand after forgetting the pull
# copies yesterday. Both halves of that have cost a deploy.
#
# So: if a file outside the named list differs, do it here, after the pull that
# has already happened, rather than leaving it to be remembered.
$whole = Join-Path $repo "tools\start\push-to-server.ps1"
$alsoNeeded = @("app.py", "estimate_routes.py", "estimating_job_tools.py",
                "public_surface.py", "auth.py", "config.py")
$drifted = @()
foreach ($name in $alsoNeeded) {
    $mine = Join-Path (Join-Path $repo "sdi-intelligence-backend") $name
    $theirs = "\\$Server\c$\ClaudeVision\sdi-intelligence-backend\$name"
    if (-not (Test-Path -LiteralPath $mine)) { continue }
    $a = (Get-FileHash -LiteralPath $mine -Algorithm SHA256).Hash
    $b = if (Test-Path -LiteralPath $theirs) {
            (Get-FileHash -LiteralPath $theirs -Algorithm SHA256).Hash } else { "" }
    if ($a -ne $b) { $drifted += $name }
}
if ($drifted.Count -gt 0 -and (Test-Path -LiteralPath $whole)) {
    Write-Host ""
    Write-Host "  These are not on the AM CRM list and differ from the server:" -ForegroundColor Yellow
    $drifted | ForEach-Object { Write-Host "      $_" -ForegroundColor White }
    Write-Host "  Running push-to-server.ps1 -Apply, which copies the whole folder." -ForegroundColor Yellow
    Write-Host ""
    & $whole -Apply
    if ($LASTEXITCODE -gt 0) { Die "push-to-server.ps1 stopped. Its message above says why." }
} elseif ($drifted.Count -gt 0) {
    Write-Host ""
    Write-Host "  These differ and need push-to-server.ps1, which is not at $whole" -ForegroundColor Yellow
    $drifted | ForEach-Object { Write-Host "      $_" -ForegroundColor White }
}
# It pulls too, and has already been pulled above; -Remote keeps it on the same one.
& $deploy -Server $Server -Remote $Remote
$deployed = $LASTEXITCODE
if ($deployed -eq 1) { Die "The deploy stopped. Its message above says why; nothing further was done." }
if ($deployed -eq 2) {
    Write-Host "  The deploy copied files but could not restart the service." -ForegroundColor Yellow
    Write-Host "  Carrying on to the restart below." -ForegroundColor Yellow
}

# -- 3. Restart and prove it ---------------------------------------------------
$checkScript = Join-Path $here "Check-AMCRM-Live.ps1"
if (-not (Test-Path -LiteralPath $checkScript)) {
    Write-Host ""
    Write-Host "  Check-AMCRM-Live.ps1 is missing, so nothing was verified." -ForegroundColor Yellow
    exit 0
}
if ($NoRestart) {
    Step "3. Checking (not restarting, -NoRestart)"
    Write-Host "  A Python file that was copied is NOT running until the service restarts." -ForegroundColor Yellow
    & $checkScript -Server $Server
} else {
    Step "3. Restarting and checking"
    & $checkScript -Server $Server -Restart
}

Write-Host ""
Write-Host ("=" * 68)
Write-Host "  Read section 4b above. Green there means the running service has the" -ForegroundColor Gray
Write-Host "  code that was just deployed." -ForegroundColor Gray
Write-Host "  If appportal pages changed, ask people to close the app fully and" -ForegroundColor Gray
Write-Host "  reopen it - phones cache them." -ForegroundColor Gray
Write-Host ("=" * 68)
Write-Host ""
