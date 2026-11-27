<#
.SYNOPSIS
    What this machine is, and what SDI Intelligence actually asks of it.

.DESCRIPTION
    Sizing a server from opinion produces a server sized by whoever was loudest. This
    produces the same numbers on every machine, in the same shape, so a developer laptop and
    the estimating runner can be put side by side and the difference read off.

    Two halves, and the second is the one that matters:

      SPEC   what the machine is - cores, memory, GPU, disk, the software the runner cannot
             work without. Takes seconds.
      LOAD   what a real estimating run costs it - peak memory per process, how much CPU it
             actually uses, whether it is waiting on disk. Requires a job to be running, and
             is the only half that can tell you what to buy.

    A spec taken while nothing is happening tells you what you own. Only the load half tells
    you what you need, which is why -Watch exists and why the answer is worth waiting for.

.PARAMETER Watch
    Minutes to sample under load. Run a real estimate and start this at the same time.
    Samples every 5 seconds and reports the PEAK of each figure, not the average - a run that
    needs 14 GB for ninety seconds needs 14 GB.

.PARAMETER OutDir
    Where to write the JSON and the text summary. Defaults to the user's desktop so nobody
    has to go looking for it.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\machine_profile.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\machine_profile.ps1 -Watch 45
#>
[CmdletBinding()]
param(
    [int]$Watch = 0,
    [string]$OutDir = "$env:USERPROFILE\Desktop"
)

$ErrorActionPreference = 'Continue'

# The processes an estimating run drives. Named here rather than guessed at, so a laptop that
# has never run one still reports zero for them instead of leaving them out and looking equal.
$TrackedProcesses = @('python', 'pythonw', 'EXCEL', 'SLDWORKS', 'sldworks', 'node', 'Code')

function Get-Safely {
    param([scriptblock]$Block, $Default = $null)
    try { & $Block } catch { $Default }
}

function To-GB { param($Bytes) if ($null -eq $Bytes) { return $null } [math]::Round($Bytes / 1GB, 1) }

Write-Host ""
Write-Host "SDI Intelligence - machine profile" -ForegroundColor Cyan
Write-Host "==================================" -ForegroundColor Cyan

# ── what it is ───────────────────────────────────────────────────────────────
$cs   = Get-Safely { Get-CimInstance Win32_ComputerSystem }
$os   = Get-Safely { Get-CimInstance Win32_OperatingSystem }
$cpu  = Get-Safely { @(Get-CimInstance Win32_Processor)[0] }
$cpus = Get-Safely { @(Get-CimInstance Win32_Processor) } @()
$mem  = Get-Safely { @(Get-CimInstance Win32_PhysicalMemory) } @()
$gpus = Get-Safely { @(Get-CimInstance Win32_VideoController) } @()

# AdapterRAM is a 32-bit field and lies about anything over 4 GB. The registry holds the real
# figure on every driver written this decade, so it is preferred and AdapterRAM is the fallback.
$gpuList = @()
foreach ($g in $gpus) {
    $vram = $null
    $key = Get-Safely {
        Get-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\*' -EA Stop |
            Where-Object { $_.DriverDesc -eq $g.Name } | Select-Object -First 1
    }
    if ($key -and $key.'HardwareInformation.qwMemorySize') { $vram = To-GB $key.'HardwareInformation.qwMemorySize' }
    elseif ($g.AdapterRAM -gt 0) { $vram = To-GB $g.AdapterRAM }
    $gpuList += [pscustomobject]@{
        Name = $g.Name; VRAM_GB = $vram; Driver = $g.DriverVersion
        Resolution = "$($g.CurrentHorizontalResolution)x$($g.CurrentVerticalResolution)"
    }
}

$disks = @()
foreach ($v in (Get-Safely { Get-Volume | Where-Object { $_.DriveType -eq 'Fixed' -and $_.DriveLetter } } @())) {
    $disks += [pscustomobject]@{
        Drive = "$($v.DriveLetter):"; Label = $v.FileSystemLabel
        SizeGB = To-GB $v.Size; FreeGB = To-GB $v.SizeRemaining
    }
}
# Needs admin on some builds; absence is reported rather than crashing the run.
$media = Get-Safely { (Get-PhysicalDisk | Select-Object -Expand MediaType) -join ', ' } 'not readable without admin'

# ── the software the runner cannot work without ──────────────────────────────
# Read from the uninstall keys, NOT Win32_Product: that class triggers an MSI consistency
# check on every installed product and can take minutes and repair things nobody asked it to.
$installed = @()
foreach ($root in @('HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
                    'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*')) {
    $installed += Get-Safely { Get-ItemProperty $root -EA Stop | Where-Object { $_.DisplayName } } @()
}
$keySoftware = $installed |
    Where-Object { $_.DisplayName -match 'SOLIDWORKS|Microsoft 365|Office (Professional|Standard)|Excel|Python' } |
    Select-Object DisplayName, DisplayVersion -Unique | Sort-Object DisplayName

$pythons = Get-Safely { (Get-Command python -All -EA Stop | Select-Object -Expand Source) -join '; ' } 'none on PATH'
$excelCom = Get-Safely {
    $x = New-Object -ComObject Excel.Application; $v = $x.Version
    $x.Quit(); [void][Runtime.InteropServices.Marshal]::ReleaseComObject($x); $v
} 'no Excel COM'

# ── what is running right now ────────────────────────────────────────────────
$sdiServices = Get-Safely { Get-Service | Where-Object { $_.Name -match 'SDI|Claude' } |
    Select-Object Name, Status, StartType } @()
$listening = Get-Safely {
    Get-NetTCPConnection -State Listen -EA Stop | Where-Object { $_.LocalPort -in 8071, 8072, 8000, 5000 } |
        Select-Object LocalPort, @{n = 'Process'; e = { (Get-Process -Id $_.OwningProcess -EA 0).ProcessName } }
} @()

$profile = [ordered]@{
    Collected        = (Get-Date).ToString('s')
    Machine          = $env:COMPUTERNAME
    User             = $env:USERNAME
    Role             = if ($sdiServices) { 'runner or portal host' } else { 'developer workstation' }
    Model            = "$($cs.Manufacturer) $($cs.Model)"
    OS               = "$($os.Caption) $($os.Version)"
    CPU              = $cpu.Name
    CPU_Sockets      = @($cpus).Count
    CPU_Cores        = ($cpus | Measure-Object -Property NumberOfCores -Sum).Sum
    CPU_Threads      = $cs.NumberOfLogicalProcessors
    CPU_MaxMHz       = $cpu.MaxClockSpeed
    RAM_GB           = To-GB $cs.TotalPhysicalMemory
    RAM_Sticks       = @($mem).Count
    RAM_SpeedMHz     = ($mem | Select-Object -First 1 -Expand Speed)
    RAM_FreeGB       = To-GB ($os.FreePhysicalMemory * 1KB)
    GPU              = ($gpuList | ForEach-Object { "$($_.Name) ($($_.VRAM_GB) GB)" }) -join ' | '
    Disks            = ($disks | ForEach-Object { "$($_.Drive) $($_.FreeGB)/$($_.SizeGB) GB free" }) -join ' | '
    DiskMedia        = $media
    ExcelCOM         = $excelCom
    PythonOnPath     = $pythons
    KeySoftware      = ($keySoftware | ForEach-Object { "$($_.DisplayName) $($_.DisplayVersion)" }) -join ' | '
    SDIServices      = ($sdiServices | ForEach-Object { "$($_.Name)=$($_.Status)" }) -join ' | '
    ListeningPorts   = ($listening | ForEach-Object { "$($_.LocalPort)/$($_.Process)" }) -join ' | '
}

# ── what it costs under load ─────────────────────────────────────────────────
# PEAKS, not averages. A run that needs 14 GB for ninety seconds needs 14 GB, and an average
# would hide exactly the moment that decides what to buy.
if ($Watch -gt 0) {
    Write-Host ""
    Write-Host "Sampling for $Watch minute(s). Start or continue a real estimating run now." -ForegroundColor Yellow
    $deadline = (Get-Date).AddMinutes($Watch)
    $peak = @{}
    $peakCpu = 0.0
    $minFreeMB = [double]::MaxValue
    $samples = 0

    while ((Get-Date) -lt $deadline) {
        $samples++
        $cpuNow = Get-Safely { (Get-Counter '\Processor(_Total)\% Processor Time' -EA Stop).CounterSamples[0].CookedValue } 0
        if ($cpuNow -gt $peakCpu) { $peakCpu = $cpuNow }
        $freeNow = Get-Safely { (Get-Counter '\Memory\Available MBytes' -EA Stop).CounterSamples[0].CookedValue } $null
        if ($null -ne $freeNow -and $freeNow -lt $minFreeMB) { $minFreeMB = $freeNow }

        foreach ($p in (Get-Process -Name $TrackedProcesses -EA SilentlyContinue)) {
            $mb = [math]::Round($p.WorkingSet64 / 1MB)
            if (-not $peak.ContainsKey($p.ProcessName) -or $mb -gt $peak[$p.ProcessName]) {
                $peak[$p.ProcessName] = $mb
            }
        }
        Start-Sleep -Seconds 5
    }

    $profile['Load_Samples']       = $samples
    $profile['Load_PeakCPU_Pct']   = [math]::Round($peakCpu, 1)
    $profile['Load_MinFreeRAM_GB'] = if ($minFreeMB -eq [double]::MaxValue) { $null } else { [math]::Round($minFreeMB / 1024, 1) }
    $profile['Load_PeakProcessMB'] = ($peak.GetEnumerator() | Sort-Object Value -Descending |
        ForEach-Object { "$($_.Key)=$($_.Value)MB" }) -join ' | '
} else {
    $profile['Load_Samples'] = 0
    $profile['Load_Note']    = 'Spec only. Re-run with -Watch 45 DURING an estimating run to get the figures that decide a server.'
}

# ── report ───────────────────────────────────────────────────────────────────
$obj = [pscustomobject]$profile
$obj | Format-List

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }
$stem = Join-Path $OutDir ("machine_profile_{0}_{1}" -f $env:COMPUTERNAME, (Get-Date -Format 'yyyyMMdd_HHmm'))
$obj | ConvertTo-Json -Depth 4 | Set-Content -Path "$stem.json" -Encoding UTF8
$obj | Format-List | Out-String | Set-Content -Path "$stem.txt" -Encoding UTF8

Write-Host ""
Write-Host "Written:" -ForegroundColor Green
Write-Host "  $stem.json"
Write-Host "  $stem.txt"
Write-Host ""
Write-Host "Send the .json back. Several of them collate into one table; a .txt does not." -ForegroundColor Green
