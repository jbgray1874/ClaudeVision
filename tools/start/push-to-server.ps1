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

    IT SENDS WHAT THE SERVER RUNS, NOT THE REPOSITORY. That machine serves the portal and
    QUEUES estimates; it has no SOLIDWORKS seat, no Excel and no runner, so it needs the
    backend, the start/repair scripts, and seven modules from src for the LLM drawing scan.
    Not 183 test files, not several hundred one-off probe scripts, not a prototype for another
    client. See $Include below for why those seven and no others. -All overrides it.

    It compares before it writes, so a run that copies nothing prints nothing alarming, and a
    run that copies six files tells you which six.
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [string]$Destination = "\\10.0.0.5\C$\ClaudeVision",

    # WHAT THE SERVER ACTUALLY RUNS, WHICH IS NOT MUCH.
    #
    # SDI-APP01 serves the portal and QUEUES estimates. It does not run them: no SOLIDWORKS
    # seat, no Excel, no runner. So it needs the backend, the scripts that start and repair
    # it -- and, from src, exactly SEVEN modules.
    #
    # Those seven are not a guess. estimate_routes._scan_one does sys.path.insert on src and
    # imports llm_scan_price, because the fast LLM drawing read runs ON THE SERVICE on
    # purpose -- put it on the runner and a hundred scans would file in behind a forty-minute
    # estimate. Following that import through gives the list below and nothing else.
    #
    # The first version of this script sent all 990 tracked files, which would have put 183
    # test files, several hundred one-off src/_probe_*.py scripts, a prototype for a
    # different client and a Sage X3 zip onto a production server that runs none of them.
    # tests/test_the_server_can_be_brought_up_to_date_without_copying_a_secret.py recomputes
    # the seven from the source and fails if this list drifts from what the code imports.
    [string[]]$Include = @(
        "sdi-intelligence-backend/",
        "tools/start/",
        "tools/diagnose/",
        "src/llm_scan_price.py",
        "src/llm_full_extract.py",
        "src/config.py",
        "src/bought_in_recogniser.py",
        "src/part_code_conventions.py",
        "src/department_codes.py",
        "src/supplier_reference.py"
    ),

    # Everything tracked. Here for the day the server's job changes; not the default,
    # because "copy the whole repo" is how a build box becomes a mystery.
    [switch]$All
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

if ($All) {
    # _archive is 677 files of history no running process reads.
    $considered = $tracked | Where-Object { -not $_.StartsWith("_archive/") }
    Write-Host "  -All: every tracked file, not just what the server runs." -ForegroundColor Yellow
} else {
    $considered = $tracked | Where-Object {
        $rel = $_
        $Include | Where-Object { $rel -eq $_ -or $rel.StartsWith($_) }
    }
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

# -- LEAVE THE COMMIT BEHIND, BECAUSE THE SERVER CANNOT WORK IT OUT --------------------
#
# /api/health on SDI-APP01 reported "commit": "unknown", so nothing could distinguish a
# current server from one serving files copied weeks ago -- which is the single question
# anybody asks after a deploy. app.py resolves its commit by shelling out to git, and there
# is no git on that machine.
#
# THIS script runs on the laptop, which has one. So the answer travels with the deploy
# rather than being recomputed where it cannot be. start-service.ps1 reads this file when
# git is unavailable and hands it over as SDI_COMMIT, which app.py already prefers.
#
# Written AFTER the copy: a stamp written before it would name a commit the server does not
# yet have if the copy then failed, which is worse than "unknown".
Push-Location $root
try { $sha = (& git rev-parse --short HEAD).Trim() } finally { Pop-Location }
if ($sha) {
    [System.IO.File]::WriteAllText((Join-Path $Destination ".sdi-commit"), "$sha`n")
    Write-Host "  stamped   $Destination\.sdi-commit  ($sha)"
}
Write-Host ""

# WHAT NOW NEEDS DOING, WHICH DEPENDS ON WHAT MOVED.
#
# app.py and config.py are read once when the process starts, so a changed .py that is not
# followed by a restart is a copy that did nothing. The HTML is the opposite: FileResponse
# reads it from disk on every request, so it is already live - but the BROWSER will keep
# serving its own cached copy, which looks exactly the same as a copy that did not happen.
$code = $changed | Where-Object { $_.Rel -like "*.py" }
$html = $changed | Where-Object { $_.Rel -like "*.html" }
$reqs = $changed | Where-Object { $_.Rel -like "*requirements.txt" }

# THIS ONE FIRST, BECAUSE IT IS THE ONE THAT STOPS THE SERVICE COMING BACK.
#
# A changed manifest means the server's virtualenv may be missing something the copied code
# imports. FastAPI raises AT STARTUP if an upload endpoint is declared without
# python-multipart -- so the service does not misbehave, it refuses to start, immediately
# after a copy that looked like it worked. Install before restarting, not after.
if ($reqs) {
    Write-Host "  requirements.txt changed. INSTALL BEFORE RESTARTING, on the server:" -ForegroundColor Yellow
    Write-Host "      cd C:\ClaudeVision" -ForegroundColor Yellow
    Write-Host "      .\sdi-intelligence-backend\.venv\Scripts\python.exe -m pip install -r sdi-intelligence-backend\requirements.txt" -ForegroundColor Yellow
    Write-Host "  THE SERVICE'S virtualenv, not the repo-root one. The root .venv is the ENGINE," -ForegroundColor Yellow
    Write-Host "  which the server does not have because it never runs an estimate - installing" -ForegroundColor Yellow
    Write-Host "  there fails with 'the term is not recognized', which looks like a typo." -ForegroundColor Yellow
    Write-Host "  A missing package here does not degrade the service, it prevents it starting." -ForegroundColor Yellow
    Write-Host ""
}

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
