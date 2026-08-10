<#
    Run several packs and print ONE table, for a parallel run against estimating.

        .\run-packs.ps1 11650-00-GA 11650-04-SA01 8278-01-GA 8278-02-GA
        .\run-packs.ps1 -Jobs 11650,8278 -Twice
        .\run-packs.ps1 11650-00-GA -Twice -Summary 'C:\ClaudeVision\output\week.md'

    Four packs run one at a time is four scrollbacks and no way to compare them. What a
    parallel run actually needs is the row a reviewer reads: which pack, what it costed,
    whether it blocked, and whether it gave the same answer twice.

    Everything here is run-job.ps1's resolution and run-job.ps1's engine - this only
    sequences them and reads back the lines the engine already prints. Nothing is
    recomputed, so a figure in this table cannot disagree with the run it came from.

    -Twice runs each pack through unchanged and compares. Same code, same pack, same
    answer is the property that has to hold before an estimator sees any of it; a pack
    that moves between two runs of the same code has nothing to say about accuracy yet.

    -Summary writes the table to a markdown file as well, so the week's evidence survives
    the console buffer.
#>
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)] [string[]] $Jobs,
    [switch] $Twice,
    [switch] $Deliverables,
    [string] $Summary
)

$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$main   = Join-Path $root 'src\main.py'
$runJob = Join-Path $root 'run-job.ps1'

if (-not $Jobs -or $Jobs.Count -eq 0) {
    Write-Error 'name at least one job, e.g. .\run-packs.ps1 11650-00-GA 8278-01-GA'
    exit 1
}
if (-not (Test-Path $python)) { Write-Error "no virtualenv at $python"; exit 1 }
if (-not (Test-Path $runJob)) { Write-Error "run-job.ps1 is not beside this script"; exit 1 }

# -- READ BACK WHAT THE ENGINE SAID --------------------------------------------------
# Parsed from the run's own output rather than recomputed from the JSON. A second reader
# of the same facts is how two numbers describing one run come to disagree, and this
# whole codebase has spent the week removing those.
function Read-RunFacts([string[]] $lines) {
    $facts = [ordered]@{
        unit = ''; material = ''; labour = ''
        blocking = ''; warnings = ''; workbook = ''
        bomOwned = ''; bomRows = ''
    }
    foreach ($l in $lines) {
        # [^\d]* RATHER THAN .? FOR THE CURRENCY MARK. The engine prints "GBP12.99"; a
        # console in the wrong code page renders that as two characters ("the mojibake form12.99"), which
        # is exactly what this machine's output shows. A single-character wildcard matches
        # the first spelling and silently fails on the second, and a failed parse here
        # produces a blank cell that reads like a free pack.
        if ($l -match 'stamped real totals into JSON:\s*material\s*[^\d]*([\d.]+),\s*labour\s*[^\d]*([\d.]+),\s*unit\s*[^\d]*([\d.]+)') {
            $facts.material = $Matches[1]; $facts.labour = $Matches[2]; $facts.unit = $Matches[3]
        }
        elseif ($l -match '\[invariants\]\s*(\d+)\s*blocking.*?(\d+)\s*warning') {
            $facts.blocking = $Matches[1]; $facts.warnings = $Matches[2]
        }
        elseif ($l -match 'AI Estimate Sheet:\s*(.+\.xlsx)') {
            $facts.workbook = $Matches[1].Trim()
        }
        elseif ($l -match '\[bom\]\s*(\d+)/(\d+) row\(s\) traced to a sheet;\s*(\d+) carry') {
            # The line that told us the hierarchy was missing on 12392. Worth a column of
            # its own: rows with no owner are how bought-in nodes end up disconnected.
            $facts.bomRows = $Matches[2]; $facts.bomOwned = $Matches[3]
        }
    }
    return $facts
}

$results = @()
foreach ($job in $Jobs) {
    Write-Host "`n=============================================================" -ForegroundColor Cyan
    Write-Host " $job" -ForegroundColor Cyan
    Write-Host "=============================================================" -ForegroundColor Cyan

    # RESOLVE THROUGH run-job.ps1's RULES, NOT A SECOND COPY OF THEM. A bare job number
    # has to mean the same thing to both scripts, and the way to guarantee that is one
    # implementation - so this asks run-job.ps1 to do the run.
    #
    # A HASHTABLE, NOT AN ARRAY. Splatting an array passes its elements POSITIONALLY, so
    # @('-Job', $job) binds the literal string "-Job" to the first parameter and leaves the
    # job with nowhere to go: "a positional parameter cannot be found that accepts argument
    # '11650-00-GA'". Only a hashtable splats by NAME.
    $folder = & $runJob -Job $job -ResolveOnly 2>$null | Select-Object -Last 1
    if (-not $folder) {
        Write-Host "could not resolve '$job' - run .\run-job.ps1 $job on its own to see why" -ForegroundColor Red
        $results += [pscustomobject]@{
            Job = $job; Unit = ''; Material = ''; Labour = ''; Blocking = ''
            Warnings = ''; 'BOM owned' = ''; Reproducible = 'not run'; Workbook = ''
        }
        continue
    }
    Write-Host "job: $folder" -ForegroundColor DarkGray

    $engineArgs = @($main, '--job', $folder, '--generate-ai-spreadsheet')
    if ($Deliverables) { $engineArgs += '--deliverables' }

    # THE ENGINE IS RUN HERE, THE FOLDER IS RESOLVED THERE. run-job.ps1 prints everything
    # through Write-Host, which writes to the HOST and never to the output stream, so a
    # caller cannot capture a run through it - the first version of this produced a table
    # of blank cells while the runs behind it were perfectly fine, which reads exactly like
    # four free packs. Asking it only for the folder keeps ONE resolver and lets this
    # script capture what the engine says.
    $captured1 = & $python @engineArgs 2>&1
    $captured1 | Out-Host
    $f1 = Read-RunFacts ($captured1 | ForEach-Object { "$_" })

    $reproducible = 'not tested'
    if ($Twice) {
        Write-Host "`n--- second run (same code, same pack) ---" -ForegroundColor DarkGray
        $captured2 = & $python @engineArgs 2>&1
        $captured2 | Out-Host
        $f2 = Read-RunFacts ($captured2 | ForEach-Object { "$_" })
        if ($f1.unit -and $f1.unit -eq $f2.unit) { $reproducible = 'IDENTICAL' }
        elseif (-not $f1.unit -or -not $f2.unit)  { $reproducible = 'no total read' }
        else { $reproducible = "DIFFERENT ($($f1.unit) vs $($f2.unit))" }
    }

    $results += [pscustomobject]@{
        Job          = $job
        Unit         = $f1.unit
        Material     = $f1.material
        Labour       = $f1.labour
        Blocking     = $f1.blocking
        Warnings     = $f1.warnings
        'BOM owned'  = if ($f1.bomRows) { "$($f1.bomOwned)/$($f1.bomRows)" } else { '' }
        Reproducible = $reproducible
        Workbook     = $f1.workbook
    }
}

Write-Host "`n`n================= PARALLEL RUN =================" -ForegroundColor Cyan
$results | Format-Table Job, Unit, Material, Labour, Blocking, Warnings, 'BOM owned', Reproducible -AutoSize | Out-Host

Write-Host 'Workbooks:' -ForegroundColor Cyan
foreach ($r in $results) {
    if ($r.Workbook) { Write-Host "    $($r.Job): $($r.Workbook)" }
    else { Write-Host "    $($r.Job): NO WORKBOOK WRITTEN" -ForegroundColor Red }
}

# WHAT A BLANK COLUMN MEANS. An empty Unit is not a free pack - it is a run whose totals
# line never appeared, which is a failed or half-finished run wearing the same face as a
# cheap one. Said out loud, because a table of blanks reads as success at a glance.
$missing = @($results | Where-Object { -not $_.Unit })
if ($missing.Count) {
    Write-Host "`n$($missing.Count) pack(s) produced NO unit total - those runs did not finish," -ForegroundColor Red
    Write-Host 'they were not free. Scroll back to the pack named above for the reason.'
}
$blocked = @($results | Where-Object { $_.Blocking -and [int]$_.Blocking -gt 0 })
if ($blocked.Count) {
    Write-Host "`n$($blocked.Count) pack(s) carry blocking findings - provisional, not a quote." -ForegroundColor Yellow
}

if ($Summary) {
    $md = @()
    $md += "# Parallel run - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    $md += ''
    $md += '| Job | Unit | Material | Labour | Blocking | Warnings | BOM owned | Reproducible |'
    $md += '|---|---|---|---|---|---|---|---|'
    foreach ($r in $results) {
        $md += "| $($r.Job) | $($r.Unit) | $($r.Material) | $($r.Labour) | $($r.Blocking) | $($r.Warnings) | $($r.'BOM owned') | $($r.Reproducible) |"
    }
    $md += ''
    $md += '## Workbooks'
    foreach ($r in $results) {
        $md += "- **$($r.Job)**: $(if ($r.Workbook) { $r.Workbook } else { 'NO WORKBOOK WRITTEN' })"
    }
    $md += ''
    $md += 'Every figure above is read back from the run''s own output, not recomputed.'
    $md += 'Provisional until the blocking findings are cleared - not a quote.'
    $dir = Split-Path $Summary -Parent
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $md -join "`r`n" | Set-Content -LiteralPath $Summary -Encoding UTF8
    Write-Host "`nSummary written: $Summary" -ForegroundColor Cyan
}
