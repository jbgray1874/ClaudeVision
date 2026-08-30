# ==============================================================================
# SDI-Intelligence-WindowsService.ps1
# SDI Intelligence Portal - Intune Platform Script
#
# PURPOSE: Downloads NSSM, registers the SDI Intelligence portal as a
#          Windows Service that auto-starts on reboot.
#
# DEPLOY TO: James Gray's device only (DESKTOP-GFAAP80)
# RUN AS:    SYSTEM
# 64-BIT:    Yes
#
# SAFE TO RE-RUN: yes - checks if service is already running correctly first
# ==============================================================================

$ServiceName = "SDIIntelligence"
$DisplayName = "SDI Intelligence Portal"
$AppDir      = "C:\ClaudeVision\sdi-intelligence-backend"
$PythonExe   = "$AppDir\.venv\Scripts\python.exe"
$AppScript   = "$AppDir\app.py"
$NssmDir     = "C:\tools\nssm-2.24\win64"
$NssmExe     = "$NssmDir\nssm.exe"
$NssmZip     = "C:\tools\nssm.zip"
$NssmUrl     = "https://nssm.cc/release/nssm-2.24.zip"

function Write-Log($msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg"
}

try {
    # ?? Check if already running correctly ????????????????????????????????????
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc -and $svc.Status -eq "Running") {
        $startType = (Get-WmiObject Win32_Service -Filter "Name='$ServiceName'").StartMode
        if ($startType -eq "Auto") {
            Write-Log "Service already running and set to auto-start - no change needed"
            Exit 0
        }
    }

    # ?? Verify prerequisites ??????????????????????????????????????????????????
    if (-not (Test-Path $PythonExe)) {
        Write-Log "ERROR: Python venv not found at $PythonExe - aborting"
        Exit 1
    }
    if (-not (Test-Path $AppScript)) {
        Write-Log "ERROR: app.py not found at $AppScript - aborting"
        Exit 1
    }
    Write-Log "Prerequisites verified"

    # ?? Download NSSM if needed ???????????????????????????????????????????????
    if (-not (Test-Path $NssmExe)) {
        Write-Log "Downloading NSSM..."
        New-Item -ItemType Directory -Path "C:\tools" -Force | Out-Null
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing -ErrorAction Stop
        Expand-Archive -Path $NssmZip -DestinationPath "C:\tools" -Force
        Remove-Item $NssmZip -Force -ErrorAction SilentlyContinue
        Write-Log "NSSM downloaded and extracted"
    } else {
        Write-Log "NSSM already present"
    }

    if (-not (Test-Path $NssmExe)) {
        Write-Log "ERROR: NSSM not found after download - aborting"
        Exit 1
    }

    # ?? Remove existing service if present ????????????????????????????????????
    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Log "Removing existing service..."
        if ($existing.Status -eq "Running") {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        }
        & $NssmExe remove $ServiceName confirm | Out-Null
        Start-Sleep -Seconds 2
    }

    # ?? Install and configure service ?????????????????????????????????????????
    Write-Log "Installing service..."
    & $NssmExe install     $ServiceName $PythonExe $AppScript
    & $NssmExe set         $ServiceName AppDirectory  $AppDir
    & $NssmExe set         $ServiceName DisplayName   $DisplayName
    & $NssmExe set         $ServiceName Description   "SDI Intelligence AI Portal and Estimating Engine"
    & $NssmExe set         $ServiceName Start         SERVICE_AUTO_START
    & $NssmExe set         $ServiceName ObjectName    LocalSystem
    & $NssmExe set         $ServiceName AppExit       Default Restart
    & $NssmExe set         $ServiceName AppRestartDelay 5000

    # Log output to the existing logs folder
    $LogDir = "C:\ClaudeVision\output\logs"
    if (Test-Path $LogDir) {
        & $NssmExe set $ServiceName AppStdout        "$LogDir\sdi_service.log"
        & $NssmExe set $ServiceName AppStderr        "$LogDir\sdi_service_error.log"
        & $NssmExe set $ServiceName AppRotateFiles   1
        & $NssmExe set $ServiceName AppRotateSeconds 86400
    }

    Write-Log "Service configured - starting..."
    Start-Service -Name $ServiceName -ErrorAction Stop
    Start-Sleep -Seconds 5

    # ?? Verify ????????????????????????????????????????????????????????????????
    $svc = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($svc.Status -eq "Running") {
        $portCheck = Test-NetConnection -ComputerName 127.0.0.1 -Port 8071 -WarningAction SilentlyContinue
        if ($portCheck.TcpTestSucceeded) {
            Write-Log "SUCCESS: Service running and port 8071 responding"
        } else {
            Write-Log "SUCCESS: Service running (port 8071 may take a few seconds)"
        }
        Exit 0
    } else {
        Write-Log "FAILED: Service status is '$($svc.Status)'"
        Exit 1
    }

} catch {
    Write-Log "ERROR: $_"
    Exit 1
}
