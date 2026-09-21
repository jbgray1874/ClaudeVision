<#
.SYNOPSIS
    Register the once-a-day job that splits scanned delivery notes into SplitScan.

.DESCRIPTION
    James Gray, 21 September 2026: "We get a number of these each day and we want to have a
    process that runs once a day and splits each delivery note out to a new folder
    K:\Logistics\Scans\SplitScan with a delivery note number as the file name and client
    name if we can find it."

    Registers a Scheduled Task that runs split_delivery_notes.py once a day. Run it again to
    change the time or the folders; it replaces the task rather than adding a second one.

.PARAMETER Source
    The folder the scanner writes into. Required, because guessing it is how a job runs every
    night against an empty directory and nobody notices for a fortnight.

.PARAMETER Out
    Where the split notes go. Defaults to K:\Logistics\Scans\SplitScan.

.PARAMETER At
    Time of day, 24h. Defaults to 06:30 — before the office opens, after the night's scanning.

.PARAMETER RunAsUser
    The account the task runs as. It needs to reach BOTH folders: a task running as SYSTEM
    cannot see a mapped drive, which is the usual reason a working script does nothing on a
    schedule. Defaults to the current user, who demonstrably can reach K: or you would not be
    reading this there.

.EXAMPLE
    .\Install-SplitScanTask.ps1 -Source "K:\Logistics\Scans\Inbox"

.EXAMPLE
    .\Install-SplitScanTask.ps1 -Source "K:\Logistics\Scans\Inbox" -At 05:45 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [string]$Out = 'K:\Logistics\Scans\SplitScan',
    [string]$At = '06:30',
    [string]$RunAsUser = "$env:USERDOMAIN\$env:USERNAME",
    [string]$TaskName = 'SDI Split Delivery Note Scans'
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$script = Join-Path $here 'split_delivery_notes.py'

if (-not (Test-Path $script)) { throw "Cannot find $script" }

# ── The things that actually stop this working, checked before the task is made ──────
#
# Every one of these has a silent failure mode on a schedule: a task that runs, exits 0 and
# does nothing. Better to refuse now, at a console, with a person watching.

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) { $python = (Get-Command py -ErrorAction SilentlyContinue).Source }
if (-not $python) { throw 'Python is not on PATH. Install it, or edit this script to give the full path.' }

$tess = (Get-Command tesseract -ErrorAction SilentlyContinue).Source
if (-not $tess) {
    throw @'
Tesseract is not on PATH, and the scans have no text layer at all, so nothing can be read
without it. Install it (winget install UB-Mannheim.TesseractOCR) and make sure its folder is
on the system PATH, not just yours -- a scheduled task does not get your profile's PATH.
'@
}

foreach ($folder in @($Source, $Out)) {
    if (-not (Test-Path $folder)) {
        if ($PSCmdlet.ShouldProcess($folder, 'Create folder')) {
            New-Item -ItemType Directory -Path $folder -Force | Out-Null
        }
    }
}

Write-Host "python    : $python"
Write-Host "tesseract : $tess"
Write-Host "source    : $Source"
Write-Host "out       : $Out"
Write-Host "runs at   : $At daily, as $RunAsUser"

$arguments = '"{0}" --source "{1}" --out "{2}"' -f $script, $Source, $Out
$action    = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $here
$trigger   = New-ScheduledTaskTrigger -Daily -At $At
# StartWhenAvailable so a machine that was off at 06:30 still does the day's scans when it
# comes back, rather than skipping a day quietly.
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable `
                                          -MultipleInstances IgnoreNew `
                                          -ExecutionTimeLimit (New-TimeSpan -Hours 2)

if ($PSCmdlet.ShouldProcess($TaskName, 'Register scheduled task')) {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
                           -Settings $settings -User $RunAsUser -RunLevel Limited `
                           -Description 'Splits the day''s scanned delivery notes into one PDF per note.' `
                           -Force | Out-Null
    Write-Host ''
    Write-Host "Registered '$TaskName'."
    Write-Host 'Try it now without writing anything:'
    Write-Host "  $python `"$script`" --source `"$Source`" --out `"$Out`" --dry-run"
    Write-Host 'Run it for real once:'
    Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
}
