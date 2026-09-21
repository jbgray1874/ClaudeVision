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
    The folder the scanner writes into. Omit it and the splitter reads SDI_SCAN_SOURCE_DIR
    from the project's .env, which is where these belong.

    NOTE the output folder sits INSIDE this one. The splitter excludes it by name, so the job
    cannot read back what it just wrote -- but if you point -Source somewhere else, keep -Out
    inside it or beside it, not the other way round.

.PARAMETER Out
    Where the split notes go. Omit it and the splitter reads SDI_SCAN_SPLIT_DIR from .env.

    THERE IS NO GUESSED DEFAULT, HERE OR IN THE SCRIPT. This installer used to repeat
    \\sdi-dc01\shareddata$\Logistics\Scans, reasoned from the estimating share and the drive
    letter in Explorer. It was wrong, and the job CREATED that tree rather than refusing it --
    after which the folder existed, Test-Path answered True, and nobody suspected the code of
    having made it. A guess repeated in a second file is a guess that outlives its correction.

    A UNC PATH, NOT K:. A mapped drive belongs to a logged-on session, and a scheduled task
    does not have one -- so K:\... is not there when this runs. Give both folders as UNC
    paths or this will appear to work and file nothing anybody can find.

.PARAMETER At
    Time of day, 24h. Defaults to 06:30 — before the office opens, after the night's scanning.

.PARAMETER RunAsUser
    The account the task runs as. It needs to reach BOTH folders: a task running as SYSTEM
    cannot see a mapped drive, which is the usual reason a working script does nothing on a
    schedule. Defaults to the current user, who demonstrably can reach K: or you would not be
    reading this there.

.EXAMPLE
    .\Install-SplitScanTask.ps1

.EXAMPLE
    .\Install-SplitScanTask.ps1 -At 05:45 -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    # Empty means "ask the config", which is the only place these live. See .PARAMETER Out.
    [string]$Source = '',
    [string]$Out = '',
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

# ── DO NOT CREATE WHAT YOU WERE ASKED TO CHECK ───────────────────────────────────────
#
# This used to be `New-Item -Force` on both folders, which builds every missing parent. A
# guessed path therefore became a real, empty folder tree on the share -- after which it
# existed, Test-Path answered True, and the splitter reported a quiet day for ever.
#
# The source folder is the scanner's and must already be there. The output folder is ours to
# make, but only inside a parent that exists.
foreach ($folder in @($Source, $Out)) {
    if (-not $folder) { continue }
    if (Test-Path $folder) { continue }
    $parent = Split-Path -Parent $folder
    if (-not (Test-Path $parent)) {
        throw @"
$folder is not there, and neither is $parent.
Refusing to create it: a path with a typo in it would be BUILT rather than refused, and the
job would then find it, see nothing in it, and report an empty day's post for ever.
Check the path. To get the real UNC name behind a mapped drive, in a NORMAL (not
Administrator) shell:
    (Get-PSDrive K).DisplayRoot
    Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='K:'" | Select-Object ProviderName
"net use" shows nothing for a drive mapped by Group Policy or a logon script, so an empty
list there does not mean the drive is not mapped.
"@
    }
    if ($folder -eq $Source) {
        throw "$Source does not exist. That is the scanner's folder -- this will not create it."
    }
    if ($PSCmdlet.ShouldProcess($folder, 'Create folder')) {
        New-Item -ItemType Directory -Path $folder | Out-Null
    }
}

Write-Host "python    : $python"
Write-Host "tesseract : $tess"
Write-Host "source    : $(if ($Source) { $Source } else { 'from SDI_SCAN_SOURCE_DIR in .env' })"
Write-Host "out       : $(if ($Out) { $Out } else { 'from SDI_SCAN_SPLIT_DIR in .env' })"
Write-Host "runs at   : $At daily, as $RunAsUser"

$arguments = '"{0}"' -f $script
if ($Source) { $arguments += ' --source "{0}"' -f $Source }
if ($Out) { $arguments += ' --out "{0}"' -f $Out }
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
