<#
    Run a whole ENQUIRY folder - one drop, every job.

        .\run-enquiry.ps1 'K:\...\Live Enquiry\11650'
        .\run-enquiry.ps1 'K:\...\11650' -Qty '11650-00-GA=45,11650-04-SA01=5'
        .\run-enquiry.ps1 'K:\...\11650' -Qty '...' -Twice -Summary 'C:\ClaudeVision\output\11650.md'

    AN ENQUIRY IS A FOLDER, AND EACH SUB-FOLDER IS ONE JOB. Estimating drops a customer's
    request as a folder on the share; each immediate sub-folder is one job, and the sub-folder
    name is the job identity. This reads that structure, prints which jobs will run and at what
    quantity, and hands them to run-packs.ps1 - the SAME per-job engine as run-job.ps1. Nothing
    is recomputed here; this only turns a folder into the argument list run-packs already
    understands.

    A MALFORMED DROP RUNS NOTHING. A drawing loose at the enquiry top (which job is it?), or a
    job folder with no drawing (priced at what?), refuses the whole enquiry with its reason
    printed - rather than silently running three of four jobs, which under-scopes the quote. Fix
    the drop and run again.

    -Qty sets per-job order quantities by folder name, 'NAME=QTY,NAME=QTY'. A job left out is
    costed at the quantity the engine infers, and the plan says so. Setup is amortised over the
    quantity, so 45 cabinets and 5 sets of side panels are one enquiry and two demand figures -
    give each its own.

    -Twice / -Deliverables / -Summary are passed straight through to run-packs.ps1.
#>
param(
    [Parameter(Position = 0, Mandatory = $true)] [string] $Enquiry,
    [string] $Qty,
    [switch] $Twice,
    [switch] $Deliverables,
    [string] $Summary
)

$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$python  = Join-Path $root '.venv\Scripts\python.exe'
$main    = Join-Path $root 'src\main.py'
$runPack = Join-Path $root 'run-packs.ps1'

if (-not (Test-Path $python))  { Write-Error "no virtualenv at $python"; exit 1 }
if (-not (Test-Path $runPack)) { Write-Error "run-packs.ps1 is not beside this script"; exit 1 }

# -- ASK THE ENGINE WHAT THE ENQUIRY CONTAINS --
# main.py --enquiry reads the folder tree and prices nothing. It prints a human summary AND a
# machine-readable plan block; we show the human part and parse the block. One reader of the
# folder, and it is the same module a future portal would call.
$mainArgs = @('--enquiry', $Enquiry)
if ($Qty) { $mainArgs += @('--enquiry-qty', $Qty) }

$lines = & $python $main @mainArgs 2>&1
$lines | ForEach-Object { Write-Host $_ }

# Everything between the markers is one run-packs argument per line, and nothing else. An empty
# block means the enquiry was refused - the reasons are already on screen above.
$inPlan = $false
$plan = @()
foreach ($line in $lines) {
    $text = "$line"
    if ($text -eq '--- ENQUIRY RUN PLAN ---')     { $inPlan = $true;  continue }
    if ($text -eq '--- END ENQUIRY RUN PLAN ---') { $inPlan = $false; continue }
    if ($inPlan -and $text.Trim()) { $plan += $text.Trim() }
}

if ($plan.Count -eq 0) {
    Write-Host ''
    Write-Host 'Nothing to run - the enquiry was refused above. Fix the drop and run again.' -ForegroundColor Yellow
    exit 1
}

Write-Host ''
Write-Host "Running $($plan.Count) job(s) from this enquiry through run-packs.ps1..." -ForegroundColor Cyan

# -- HAND THE PLAN TO THE PROVEN SEQUENCER --
$packArgs = @{}
if ($Twice)        { $packArgs['Twice'] = $true }
if ($Deliverables) { $packArgs['Deliverables'] = $true }
if ($Summary)      { $packArgs['Summary'] = $Summary }
& $runPack @plan @packArgs
exit $LASTEXITCODE
