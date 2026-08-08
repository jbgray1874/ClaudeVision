<#
    Run one job through the estimator.

        .\run-job.ps1 12392                        # a bare job number is enough
        .\run-job.ps1 'C:\ClaudeVision\input\drawings\12392-02'
        .\run-job.ps1 12392 -Deliverables
        .\run-job.ps1 12392 -Twice                 # reproducibility check

    A BARE JOB NUMBER RESOLVES. Typing the full path is where this goes wrong: three
    sessions in a row were lost to a placeholder path being pasted verbatim, and the
    script's only answer was "no such job folder" — true, unhelpful, and identical
    whether the pack was missing, on a share that had not mounted, or simply spelled
    differently. Give it 12392 and it searches:

        input\drawings\                            the local working copy
        $env:SDI_JOBS_ROOT                         set this to the estimating share
        the current directory

    and, when nothing matches, PRINTS WHAT IT DID FIND so the next attempt is a
    correction rather than another guess.

    To make the share searchable, set it once per machine:

        setx SDI_JOBS_ROOT "K:\Shared\Estimating\<your live enquiry folder>"

    (reopen the console afterwards — setx does not affect the session that ran it).

    Exists because a long command line pasted into a console loses its first character
    often enough to matter, and PowerShell then runs the fragment: "C:\ClaudeVision\..."
    arriving as ":\ClaudeVision\..." leaves a bare "r 42", which is Invoke-History, which
    silently re-runs whatever command 42 happened to be. Twice in one day that looked like
    the engine hanging when it was replaying an old run.

    -Twice runs the same pack through unchanged and prints both totals. Same code, same
    pack, same answer is the property the caches exist for, and nobody had actually
    measured it.
#>
param(
    [Parameter(Mandatory = $true, Position = 0)] [string] $Job,
    [switch] $Deliverables,
    [switch] $Twice
)

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$main   = Join-Path $root 'src\main.py'

if (-not (Test-Path $python)) { Write-Error "no virtualenv at $python"; exit 1 }

# ── RESOLVE THE JOB ─────────────────────────────────────────────────────────────────
# Where a pack can live, most specific first. SDI_JOBS_ROOT is how a machine points at
# the estimating share without this script carrying anybody's drive letter — a hardcoded
# path is exactly the kind of per-site detail that stops working on the next machine.
$searchRoots = @(
    (Join-Path $root 'input\drawings')
    $env:SDI_JOBS_ROOT
    (Get-Location).Path
) | Where-Object { $_ -and (Test-Path $_) }

function Resolve-Job([string] $wanted) {
    if (Test-Path $wanted) { return (Resolve-Path $wanted).Path }

    # A bare number, or a partial code. Prefer an exact folder name, then a prefix match,
    # so '12392' finds '12392-02' but '12392-02' is never answered with '12392-04'.
    $leaf = Split-Path $wanted -Leaf
    foreach ($mode in @('exact', 'prefix')) {
        foreach ($r in $searchRoots) {
            $hits = @(Get-ChildItem -LiteralPath $r -Directory -ErrorAction SilentlyContinue |
                      Where-Object {
                          if ($mode -eq 'exact') { $_.Name -ieq $leaf }
                          else { $_.Name -ilike "$leaf*" }
                      })
            if ($hits.Count -eq 1) { return $hits[0].FullName }
            if ($hits.Count -gt 1) {
                Write-Host "'$leaf' matches more than one folder under ${r}:" -ForegroundColor Yellow
                $hits | ForEach-Object { Write-Host "    $($_.FullName)" }
                Write-Error 'Name the one you want.'
                exit 1
            }
        }
    }
    return $null
}

$resolved = Resolve-Job $Job
if (-not $resolved) {
    # SAY WHAT IS THERE. "No such job folder" is true of a typo, an unmounted share and a
    # pack that was never copied down, and those need three different next actions.
    Write-Host "no job folder matching '$Job'." -ForegroundColor Red
    Write-Host "`nSearched:" -ForegroundColor Cyan
    foreach ($r in $searchRoots) { Write-Host "    $r" }
    if (-not $env:SDI_JOBS_ROOT) {
        Write-Host "`nSDI_JOBS_ROOT is not set, so the estimating share was not searched." -ForegroundColor Yellow
        Write-Host '    setx SDI_JOBS_ROOT "K:\Shared\Estimating\<your live enquiry folder>"'
        Write-Host '    (then reopen this console)'
    }
    # Collected, then printed. Assigning to an outer variable from inside a pipeline
    # script block is a scoping question with a version-dependent answer, and this file
    # exists because a console surprise cost a day.
    $found = @()
    foreach ($r in $searchRoots) {
        $found += @(Get-ChildItem -LiteralPath $r -Directory -ErrorAction SilentlyContinue |
                    Select-Object -First 25 -ExpandProperty FullName)
    }
    Write-Host "`nJobs found:" -ForegroundColor Cyan
    if ($found.Count -eq 0) {
        Write-Host '    (none — no pack has been copied down yet)'
    } else {
        foreach ($f in $found) { Write-Host "    $f" }
    }
    exit 1
}
$Job = $resolved
Write-Host "job: $Job" -ForegroundColor DarkGray

$estArgs = @($main, '--job', $Job, '--generate-ai-spreadsheet')
if ($Deliverables) { $estArgs += '--deliverables' }

function Invoke-Run([string] $label) {
    Write-Host "`n=== $label ===`n" -ForegroundColor Cyan
    & $python @estArgs 2>&1 | Tee-Object -Variable out | Out-Host
    ($out | Select-String 'stamped real totals into JSON').Line
}

$first = Invoke-Run 'run 1'
if ($Twice) {
    $second = Invoke-Run 'run 2 (same code, same pack)'
    Write-Host "`n=== REPRODUCIBILITY ===" -ForegroundColor Cyan
    Write-Host "run 1: $first"
    Write-Host "run 2: $second"
    if ($first -eq $second) {
        Write-Host 'IDENTICAL — the caches and the deterministic path hold.' -ForegroundColor Green
    } else {
        Write-Host 'DIFFERENT — same code and same pack produced two answers.' -ForegroundColor Red
    }
}

Write-Host "`nMeasure it:" -ForegroundColor Cyan
Write-Host "  $python $(Join-Path $root 'tools\three_numbers.py')"
