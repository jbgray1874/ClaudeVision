<#
.SYNOPSIS
    One presence cycle: ask BrightHR who is clocked in, push it to InVentry.

.DESCRIPTION
    What the scheduled task runs. Two steps:

      1. hr_blip.py         - query BrightHR Blip, write the on-site snapshot
      2. hr_onsite_push.py  - reconcile InVentry's register against it

    Defaults to a DRY RUN. Pass -Apply to write to InVentry.

    Exit codes are meaningful, because Task Scheduler records them:
      0  clean
      2  ran, but something was suppressed or partially failed
      1  aborted without writing - a guard tripped, a system was unreachable,
         or the interpreter could not be found

    Everything printed here is also appended to $LogFile. Task Scheduler
    discards a task's console output, so without that file a failed run leaves
    nothing behind but an exit code.

    If the Blip query is degraded or the snapshot is stale, the push refuses
    rather than publishing an under-reported on-site list. That is deliberate:
    an incomplete evacuation list is worse than one that has not moved.

.EXAMPLE
    .\run_presence_sync.ps1
    .\run_presence_sync.ps1 -Apply
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    # Left blank on purpose: hard-coding one checkout's venv breaks every other
    # checkout. Resolved below, and reported when it cannot be found.
    [string]$Python,
    # No default here. A default of "$PSScriptRoot\.." came back as C:\ under
    # Task Scheduler on the live desktop (14 Oct): $PSScriptRoot was empty in
    # the param block, "\.." resolved to the drive root, and every scheduled
    # run looked for C:\hr_blip.py while working perfectly by hand. The
    # installer now passes this explicitly; the body below falls back to the
    # script's own path, and checks the answer.
    [string]$BackendDir,
    [string]$LogFile = "C:\SDIIntelligence\hr\snapshots\presence_sync.log"
)

$ErrorActionPreference = "Continue"

function Say($text) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $text"
    Write-Host $line
    try {
        $dir = Split-Path $LogFile -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding utf8
    } catch {
        # A log we cannot write must not stop a fire-roll update.
    }
}

# ── Find the backend ─────────────────────────────────────────────────────
if (-not $BackendDir) {
    $self = if ($MyInvocation.MyCommand.Path) { $MyInvocation.MyCommand.Path } else { $PSCommandPath }
    if ($self) { $BackendDir = Split-Path (Split-Path $self -Parent) -Parent }
}
# Checked, not trusted. Without this a wrong folder surfaced only as Python's
# "can't open file" - which exits 2, the same code this script uses for a
# degraded Blip query, so a run that did nothing at all was logged as partial.
foreach ($needed in @("hr_blip.py", "hr_onsite_push.py")) {
    if (-not $BackendDir -or -not (Test-Path (Join-Path $BackendDir $needed))) {
        Say "ABORT: $needed not found in '$BackendDir'. The backend folder was resolved"
        Say "       wrongly - re-run deploy\install_presence_task.ps1, which passes"
        Say "       -BackendDir explicitly. Nothing was sent to InVentry."
        exit 1
    }
}
$BackendDir = (Resolve-Path $BackendDir).Path
Set-Location $BackendDir

# ── Find the interpreter ─────────────────────────────────────────────────
# Without this the script used to call a path that may not exist. PowerShell
# reports that as a non-terminating error, leaves $LASTEXITCODE untouched from
# whatever ran before, and the script sails on to the push with no Blip data -
# the exact "job runs, nothing happens" failure.
if (-not $Python) {
    $repoRoot = Split-Path $BackendDir -Parent
    $candidates = @(
        $(if ($env:VIRTUAL_ENV) { Join-Path $env:VIRTUAL_ENV "Scripts\python.exe" }),
        (Join-Path $BackendDir ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot  ".venv\Scripts\python.exe"),
        (Join-Path $repoRoot  "venv\Scripts\python.exe")
    ) | Where-Object { $_ }
    $Python = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
    if (-not $Python) {
        $Python = (Get-Command python.exe -ErrorAction SilentlyContinue |
                   Select-Object -First 1 -ExpandProperty Source)
    }
}
if (-not $Python -or -not (Test-Path $Python)) {
    Say "ABORT: no Python interpreter found. Looked in the checkout's .venv, the"
    Say "       repository root's .venv, and PATH. Note a scheduled task running"
    Say "       as SYSTEM does not inherit your PATH - pass -Python explicitly."
    exit 1
}

Say "presence sync starting$(if (-not $Apply) { ' (dry run)' })"
Say "  backend $BackendDir"
Say "  python  $Python"

# ── 1. BrightHR ──────────────────────────────────────────────────────────
$blipOut = & $Python (Join-Path $BackendDir "hr_blip.py") 2>&1
$blip = $LASTEXITCODE
$blipOut | ForEach-Object { Say "  blip| $_" }

if ($blip -eq 1) {
    Say "Blip query failed outright - not pushing anything to InVentry."
    exit 1
}
if ($blip -eq 2) {
    # Degraded: some per-employee queries failed. The push applies its own
    # guard against this, so let it decide rather than second-guessing here.
    Say "Blip query degraded - the push will decide whether to publish."
}

# ── 2. InVentry ──────────────────────────────────────────────────────────
$pushArgs = @((Join-Path $BackendDir "hr_onsite_push.py"), "--by", "scheduled task")
if ($Apply) { $pushArgs += "--apply" }

$pushOut = & $Python @pushArgs 2>&1
$push = $LASTEXITCODE
$pushOut | ForEach-Object { Say "  push| $_" }

Say "finished: blip=$blip push=$push"
exit $push
