# ==============================================================================
# Detect-SDIIntelligenceService.ps1
# SDI Intelligence Portal — Intune Proactive Remediation DETECTION script
#
# PURPOSE: Checks whether the SDI Intelligence portal is registered as a
#          Windows Service and is set to auto-start.
#
# INTUNE BEHAVIOUR:
#   Exit 0 = service exists, is auto-start and running — no remediation needed
#   Exit 1 = service missing, wrong start type, or stopped — trigger remediation
# ==============================================================================

$ServiceName = "SDIIntelligence"

try {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue

    if (-not $svc) {
        Write-Host "NOT DETECTED: Service '$ServiceName' does not exist"
        Exit 1
    }

    # Check start type is Automatic
    $startType = (Get-WmiObject Win32_Service -Filter "Name='$ServiceName'").StartMode
    if ($startType -ne "Auto") {
        Write-Host "NOT COMPLIANT: Service exists but StartMode is '$startType' (expected Auto)"
        Exit 1
    }

    # Check service is running
    if ($svc.Status -ne "Running") {
        Write-Host "NOT COMPLIANT: Service exists but status is '$($svc.Status)'"
        Exit 1
    }

    Write-Host "DETECTED: Service '$ServiceName' is registered, auto-start, and running"
    Exit 0

} catch {
    Write-Host "ERROR: $_"
    Exit 1
}
