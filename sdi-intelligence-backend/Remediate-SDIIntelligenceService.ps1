# ==============================================================================
# Remediate-SDIIntelligenceService.ps1
# SDI Intelligence Portal — Intune Proactive Remediation REMEDIATION script
#
# PURPOSE: Downloads NSSM, registers the SDI Intelligence portal as a
#          Windows Service set to auto-start, and starts it immediately.
#
# WHAT IT DOES:
#   1. Creates C:\tools if it doesn't exist
#   2. Downloads NSSM 2.24 (if not already present)
#   3. Removes any existing SDIIntelligence service (clean reinstall)
#   4. Registers the portal as a Windows Service running under SYSTEM
#   5. Sets working directory, auto-start, and display name
#   6. Starts the service
#
# PREREQUISITES ON THE HOST MACHINE:
#   - Python venv at:  C:\ClaudeVision\sdi-intelligence-backend\.venv\
#   - App entry point: C:\ClaudeVision\sdi-intelligence-backend\app.py
#
# SAFE TO RE-RUN: yes — removes and recreates the service cleanly each time
# ==============================================================================

$ServiceName  = "SDIIntelligence"
$DisplayName  = "SDI Intelligence Portal"
$AppDir       = "C:\ClaudeVision\sdi-intelligence-backend"
$PythonExe    = "$AppDir\.venv\Scripts\python.exe"
$AppScript    = "$AppDir\app.py"
$NssmDir      = "C:\tools\nssm-2.24\win64"
$NssmExe      = "$NssmDir\nssm.exe"
$NssmZip      = "C:\tools\nssm.zip"
$NssmUrl      = "https://nssm.cc/release/nssm-2.24.zip"

function Write-Log($msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg"
}

try {
    # ── Step 1: Verify prerequisites ──────────────────────────────────────────
    if (-not (Test-Path $PythonExe)) {
        Write-Log "ERROR: Python venv not found at $PythonExe — aborting"
        Exit 1
    }
    if (-not (Test-Path $AppScript)) {
        Write-Log "ERROR: app.py not found at $AppScript — aborting"
        Exit 1
    }
    Write-Log "Prerequisites verified"

    # ── Step 2: Download NSSM if needed ───────────────────────────────────────
    if (-not (Test-Path $NssmExe)) {
        Write-Log "NSSM not found — downloading..."
        New-Item -ItemType Directory -Path "C:\tools" -Force | Out-Null

        # Download with TLS 1.2
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $NssmUrl -OutFile $NssmZip -UseBasicParsing -ErrorAction Stop
        Write-Log "Downloaded NSSM zip"

        Expand-Archive -Path $NssmZip -DestinationPath "C:\tools" -Force
        Write-Log "Extracted NSSM to C:\tools"

        Remove-Item $NssmZip -Force -ErrorAction SilentlyContinue
    } else {
        Write-Log "NSSM already present at $NssmExe"
    }

    if (-not (Test-Path $NssmExe)) {
        Write-Log "ERROR: NSSM exe not found after extraction — aborting"
        Exit 1
    }

    # ── Step 3: Remove existing service if present ────────────────────────────
    $existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Log "Removing existing service '$ServiceName'..."
        if ($existing.Status -eq "Running") {
            Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
        }
        & $NssmExe remove $ServiceName confirm | Out-Null
        Start-Sleep -Seconds 2
        Write-Log "Existing service removed"
    }

    # ── Step 4: Install service ────────────────────────────────────────────────
    Write-Log "Installing service '$ServiceName'..."
    & $NssmExe install $ServiceName $PythonExe $AppScript
    Start-Sleep -Seconds 1

    # ── Step 5: Configure service ──────────────────────────────────────────────
    & $NssmExe set $ServiceName AppDirectory $AppDir
    & $NssmExe set $ServiceName DisplayName  $DisplayName
    & $NssmExe set $ServiceName Description  "SDI Intelligence AI Portal and Estimating Engine"
    & $NssmExe set $ServiceName Start        SERVICE_AUTO_START
    & $NssmExe set $ServiceName ObjectName   LocalSystem

    # Restart policy: restart automatically after 5 seconds on failure
    & $NssmExe set $ServiceName AppExit      Default Restart
    & $NssmExe set $ServiceName AppRestartDelay 5000

    # Log stdout/stderr to a file for diagnostics
    $LogDir = "C:\ClaudeVision\output\logs"
    if (Test-Path $LogDir) {
        & $NssmExe set $ServiceName AppStdout "$LogDir\sdi_intelligence_service.log"
        & $NssmExe set $ServiceName AppStderr "$LogDir\sdi_intelligence_service_error.log"
        & $NssmExe set $ServiceName AppRotateFiles 1
        & $NssmExe set $ServiceName AppRotateSeconds 86400
    }

    Write-Log "Service configured"

    # ── Step 6: Start service ──────────────────────────────────────────────────
    Write-Log "Starting service..."
    Start-Service -Name $ServiceName -ErrorAction Stop
    Start-Sleep -Seconds 5

    # ── Step 7: Verify ────────────────────────────────────────────────────────
    $svc = Get-Service -Name $ServiceName -ErrorAction Stop
    if ($svc.Status -eq "Running") {
        Write-Log "SUCCESS: Service '$ServiceName' is running"

        # Quick port check
        $portCheck = Test-NetConnection -ComputerName 127.0.0.1 -Port 8071 -WarningAction SilentlyContinue
        if ($portCheck.TcpTestSucceeded) {
            Write-Log "SUCCESS: Port 8071 is responding"
        } else {
            Write-Log "WARNING: Service running but port 8071 not yet responding (may need a few seconds)"
        }
        Exit 0
    } else {
        Write-Log "FAILED: Service status is '$($svc.Status)' after start attempt"
        Exit 1
    }

} catch {
    Write-Log "ERROR: $_"
    Exit 1
}
