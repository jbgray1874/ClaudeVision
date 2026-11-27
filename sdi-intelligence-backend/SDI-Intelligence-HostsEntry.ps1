# ==============================================================================
# SDI-Intelligence-HostsEntry.ps1
# SDI Intelligence Portal - Intune Platform Script
#
# PURPOSE: Adds sdi-intelligence.sdi.local -> 10.0.16.151 to the hosts file
#          on every SDI PC so all users can reach the portal by friendly URL.
#
# 20 Sep 2026: retargeted from 10.0.16.151 to 10.0.0.5. The service moved and
# this script did not follow, so every managed PC has been pointing the friendly
# name at a host that does not answer (DestinationHostUnreachable). Editing this
# file changes nothing by itself - it must be re-uploaded to Intune.
#
# This is a stopgap. A hosts entry on 300 devices is 300 things to keep in sync;
# a DNS A record on the DC is one, and an HTTPS hostname removes the :8071 as
# well. See APP_PORTAL_RUNBOOK.md.
#
# DEPLOY TO: All Devices
# RUN AS:    SYSTEM
# 64-BIT:    Yes
#
# SAFE TO RE-RUN: yes - never creates duplicate entries
# ==============================================================================

$CorrectIP  = "10.0.0.5"
$Hostname   = "sdi-intelligence.sdi.local"
$HostsFile  = "C:\Windows\System32\drivers\etc\hosts"
$NewLine    = "$CorrectIP`t$Hostname"

function Write-Log($msg) {
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] $msg"
}

try {
    $content = Get-Content $HostsFile -ErrorAction Stop

    # Check if already correct
    $existing = $content | Where-Object { $_ -match [regex]::Escape($Hostname) }
    if ($existing -and ($existing -match [regex]::Escape($CorrectIP))) {
        Write-Log "Already correct: '$NewLine' - no change needed"
        Exit 0
    }

    # Remove any existing (wrong or old) entry for this hostname
    $cleaned = $content | Where-Object { $_ -notmatch [regex]::Escape($Hostname) }

    # Add the correct entry
    $cleaned += $NewLine
    Set-Content -Path $HostsFile -Value $cleaned -Encoding UTF8 -ErrorAction Stop

    # Verify
    $verify = Get-Content $HostsFile | Where-Object { $_ -match [regex]::Escape($Hostname) }
    if ($verify -and ($verify -match [regex]::Escape($CorrectIP))) {
        Write-Log "SUCCESS: Added '$NewLine' to hosts file"
        Exit 0
    } else {
        Write-Log "FAILED: Entry not found after write"
        Exit 1
    }

} catch {
    Write-Log "ERROR: $_"
    Exit 1
}
