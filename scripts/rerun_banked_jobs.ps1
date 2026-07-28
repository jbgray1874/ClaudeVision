# Re-run the four banked M&S tender jobs on the current code.
#
# Regenerates for each: populated workbook, client quote HTML, job report HTML, LLM
# extract JSON. Use after pipeline changes so the deliverables and the spreadsheets
# agree, and so figures quoted in the briefing are all produced by the same build.
#
#   cd C:\ClaudeVision
#   .\scripts\rerun_banked_jobs.ps1
#
# Optional: point at a different pack root
#   .\scripts\rerun_banked_jobs.ps1 -PackRoot "C:\ClaudeVision\work\MS_Tender"

param(
    [string]$PackRoot = "C:\ClaudeVision\work\MS_Tender",
    [string]$LogDir   = "C:\ClaudeVision\work\rerun_logs",
    [int]$OrderQty    = 1,
    [string]$Customer = "M&S",
    # Limit to specific job numbers, e.g. -Jobs 0348837
    # Cocktails (0359131) is a 45-page pack and dominates the runtime, so re-running a
    # single small job is often all that is needed after a deliverable-only change.
    [string[]]$Jobs   = @("0348837", "0357299", "0357831", "0359131")
)

$ErrorActionPreference = "Continue"
$py = "C:\ClaudeVision\.venv\Scripts\python.exe"

# Pipeline flags - same set used for the banked runs
$env:SDI_APPLY_DRAWING_FACTS = "1"
$env:SDI_LLM_FULL_EXTRACT    = "1"
$env:SKIP_VISION_EXTRACTION  = "1"
$env:SCAN_DEBUG              = "1"

$jobs = $Jobs

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

Write-Host ""
Write-Host "Re-running banked jobs on commit: " -NoNewline
git -C C:\ClaudeVision log --oneline -1
Write-Host "Pack root: $PackRoot"
Write-Host "Logs:      $LogDir"
Write-Host ""

$results = @()

foreach ($job in $jobs) {
    # Find the combined/GA pack for this job number. Prefer a '-combined' pack if present
    # (the whole drawing set in one file), else the largest matching PDF.
    $cands = Get-ChildItem -Path $PackRoot -Recurse -Filter "*$job*.pdf" -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -notmatch "_quote|_report" }

    if (-not $cands) {
        Write-Host "[$job] NO PDF FOUND under $PackRoot - skipped." -ForegroundColor Red
        $results += [pscustomobject]@{ Job=$job; Status="no pdf"; Pdf=""; Log="" }
        continue
    }

    $pdf = ($cands | Where-Object { $_.Name -match "combined" } |
            Sort-Object Length -Descending | Select-Object -First 1)
    if (-not $pdf) { $pdf = ($cands | Sort-Object Length -Descending | Select-Object -First 1) }

    $log = Join-Path $LogDir "$job`_rerun.log"

    Write-Host "[$job] $($pdf.Name)" -ForegroundColor Cyan
    Write-Host "       -> $log"

    & $py src\main.py --pdf "$($pdf.FullName)" `
        --generate-ai-spreadsheet --deliverables `
        --order-qty $OrderQty --customer "$Customer" 2>&1 |
        Tee-Object -FilePath $log | Out-Null

    # Pull the authoritative stamped totals back out of the log
    $stamp = Select-String -Path $log -Pattern "stamped real totals" |
             Select-Object -Last 1 -ExpandProperty Line
    $gate  = Select-String -Path $log -Pattern "INSUFFICIENT DATA|Estimated document total" |
             Select-Object -Last 1 -ExpandProperty Line

    Write-Host "       $stamp" -ForegroundColor Green
    if ($gate) { Write-Host "       $gate" -ForegroundColor Yellow }
    Write-Host ""

    $results += [pscustomobject]@{ Job=$job; Status="ran"; Pdf=$pdf.Name; Log=$log }
}

Write-Host "================ SUMMARY ================" -ForegroundColor Cyan
$results | Format-Table -AutoSize

Write-Host "Authoritative totals from each run:" -ForegroundColor Cyan
foreach ($r in $results | Where-Object { $_.Status -eq "ran" }) {
    $line = Select-String -Path $r.Log -Pattern "stamped real totals" |
            Select-Object -Last 1 -ExpandProperty Line
    "{0}: {1}" -f $r.Job, ($line -replace '.*stamped real totals into JSON: ', '')
}
Write-Host ""
Write-Host "Deliverables (quote/report HTML) are in C:\ClaudeVision\output\estimates"
