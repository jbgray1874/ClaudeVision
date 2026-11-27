<#
    Drive AI estimates from the Live Enquiry workbook, one after another (D-420).

        cd C:\ClaudeVision
        .\run-live-enquiry.ps1 scan                    what each row would do; runs nothing
        .\run-live-enquiry.ps1 baseline                once, first: jobs already run by hand stay done
        .\run-live-enquiry.ps1 run                     queue every ready row, one at a time, then stop
        .\run-live-enquiry.ps1 run --max 1             just the next one
        .\run-live-enquiry.ps1 watch                   run, wait 15 min, read the sheet again
        .\run-live-enquiry.ps1 list                    what has run, and what it came to
        .\run-live-enquiry.ps1 qty 8188-08 1,5,10,50   quantities the sheet does not give
        .\run-live-enquiry.ps1 retry 8188-08           let a failed job run again

    A row runs when AI CHECK says YES, its note does not hold it (WAIT FOR DRAWINGS), the share
    has <Live Enquiry>\<Customer>\<Drawing No.> with drawings directly in it, and a quantity is
    stated (a Qty column on the sheet, QUANTITIES.txt in the folder, "50 off" in the
    description, or `qty`). Each is queued through the portal exactly as the page queues it,
    so the portal and a runner must be up. Every scan writes output\live_enquiry\
    live_enquiry_status.csv: every row, what it did, and why.

    Settings: config\live_enquiry_runner.example.env -> .env. The workbook is read, never
    written.
#>
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root '.venv\Scripts\python.exe'
$script = Join-Path $root 'src\live_enquiry_runner.py'
if (-not (Test-Path $python)) { Write-Error "no virtualenv at $python"; exit 1 }
& $python -u $script @args
exit $LASTEXITCODE
