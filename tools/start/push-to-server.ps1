<#
    Bring SDI-APP01 up to this checkout, when SDI-APP01 has no git.

        .\tools\start\push-to-server.ps1              # list what differs, copy nothing
        .\tools\start\push-to-server.ps1 -Apply       # copy it

    RUN THIS ON THE LAPTOP. It reads from this checkout and writes to the server's admin
    share. The server is the machine that cannot pull; the laptop is the one that can.

    WHY IT EXISTS. `git` is not on SDI-APP01, so nothing has ever reached it except by hand.
    That is why it serves pages the laptop fixed weeks ago - the menu items that "disappear"
    on the server are simply not in the copy of the HTML it has. There was no mechanism, so
    there was drift, and the drift was invisible from either machine.

    THE ONE THING THAT MUST NEVER TRAVEL IS A .env. The two machines hold DIFFERENT values:
    different file roots, different staging paths, and on the server a service account that
    the laptop does not use. Copying the laptop's over the top would replace a working
    configuration with one describing a machine it is not running on - and it would do it
    silently, because the files have the same name.

    So the file list comes from `git ls-files`. A .env is gitignored, therefore untracked,
    therefore not in the list, therefore cannot be copied. That is the guard: not a rule
    applied to the list, but the reason the list cannot contain it. There is a belt-and-braces
    check below as well, because this one is worth being obvious about.

    It compares before it writes, so a run that copies nothing prints nothing alarming, and a
    run that copies six files tells you which six.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Destination = "\\10.0.0.5\C$\ClaudeVision",
    # _archive is 677 files of history that no running process reads. Skipping it turns a
    # slow copy over SMB into a fast one.
    [string[]]$Skip = @("_archive/")
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host ""
Write-Host "PUSH TO SERVER  -  $root  ->  $Destination" -ForegroundColor Cyan
Write-Host ("-" * 72)

if (-not (Test-Path -LiteralPath $Destination)) {
    Write-Host "  Cannot reach $Destination" -ForegroundColor Red
    Write-Host "  The admin share needs local-administrator rights on the server. If it is" -ForegroundColor Red
    Write-Host "  refused, map a normal share on SDI-APP01 and pass it with -Destination." -ForegroundColor Red
    Write-Host ""
    exit 2
}

Push-Location $root
try {
    $tracked = & git ls-files
} finally {
    Pop-Location
}
if (-not $tracked) {
    Write-Host "  git ls-files returned nothing - is this a checkout?" -ForegroundColor Red
    exit 2
}

$considered = $tracked | Where-Object {
    $rel = $_
    -not ($Skip | Where-Object { $rel.StartsWith($_) })
}

# Belt and braces. A .env is untracked so it cannot be in $tracked, but this is the one
# mistake in this script that would be expensive and quiet, so it is stated rather than
# assumed. If this ever fires, something has been `git add -f`'d that should not have been.
$secrets = $considered | Where-Object { [IO.Path]::GetFileName($_) -eq ".env" }
if ($secrets) {
    Write-Host "  STOP. A .env is tracked in this repository:" -ForegroundColor Red
    $secrets | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-Host "  Copying it would overwrite the server's own configuration. Untrack it first." -ForegroundColor Red
    Write-Host ""
    exit 2
}

function Get-Sha([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

$changed = New-Object System.Collections.Generic.List[object]
$missing = 0
foreach ($rel in $considered) {
    $src = Join-Path $root ($rel -replace "/", "\")
    if (-not (Test-Path -LiteralPath $src)) { continue }
    $dst = Join-Path $Destination ($rel -replace "/", "\")
    $dstHash = Get-Sha $dst
    if ($null -eq $dstHash) { $missing++ }
    if ($dstHash -ne (Get-Sha $src)) {
        $changed.Add([pscustomobject]@{ Rel = $rel; Src = $src; Dst = $dst; New = ($null -eq $dstHash) })
    }
}

Write-Host ("  {0} tracked files considered, {1} differ ({2} not on the server at all)" -f `
    $considered.Count, $changed.Count, $missing)
Write-Host ""

if ($changed.Count -eq 0) {
    Write-Host "  The server already matches this checkout. Nothing to do." -ForegroundColor Green
    Write-Host ""
    return
}

foreach ($c in $changed) {
    $mark = "differs"
    if ($c.New) { $mark = "NEW    " }
    Write-Host ("  {0}  {1}" -f $mark, $c.Rel)
}
Write-Host ""

if (-not $Apply) {
    Write-Host "  Re-run with -Apply to copy these."
    Write-Host ""
    return
}

foreach ($c in $changed) {
    $dir = Split-Path -Parent $c.Dst
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Copy-Item -LiteralPath $c.Src -Destination $c.Dst -Force
}
Write-Host ("  copied {0} files" -f $changed.Count) -ForegroundColor Green
Write-Host ""

# WHAT NOW NEEDS DOING, WHICH DEPENDS ON WHAT MOVED.
#
# app.py and config.py are read once when the process starts, so a changed .py that is not
# followed by a restart is a copy that did nothing. The HTML is the opposite: FileResponse
# reads it from disk on every request, so it is already live - but the BROWSER will keep
# serving its own cached copy, which looks exactly the same as a copy that did not happen.
$code = $changed | Where-Object { $_.Rel -like "*.py" }
$html = $changed | Where-Object { $_.Rel -like "*.html" }

if ($code) {
    Write-Host "  Python changed, so the service must be restarted ON THE SERVER before any" -ForegroundColor Yellow
    Write-Host "  of it is read:" -ForegroundColor Yellow
    Write-Host "      .\tools\start\restart-service.ps1 -Port 8071" -ForegroundColor Yellow
    Write-Host ""
}
if ($html) {
    Write-Host "  HTML changed. No restart needed - it is read from disk per request - but do a"
    Write-Host "  hard refresh in the browser (F12, right-click reload, Empty cache and hard"
    Write-Host "  refresh), or you will be shown the old page and conclude this did not work."
    Write-Host ""
}
