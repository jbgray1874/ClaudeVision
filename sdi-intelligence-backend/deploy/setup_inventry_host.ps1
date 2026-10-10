<#
.SYNOPSIS
    Prepare a machine to talk to the InVentry Partner API.

.DESCRIPTION
    Everything a host needs before the presence sync will run: network
    reachability, the hosts entry that makes TLS verification possible, the
    certificate, and a check that .env carries the InVentry settings.

    Idempotent - safe to run repeatedly. Run it on SDI-APP01, and on any other
    machine that will run the sync, after checking out the branch.

    Why the hosts entry: InVentry's certificate is issued to CN=InVentry-PC,
    not to its IP address, so connecting by IP fails hostname verification even
    with the certificate trusted. Pointing the name at the IP lets verification
    succeed properly rather than turning it off.

.EXAMPLE
    .\setup_inventry_host.ps1
    .\setup_inventry_host.ps1 -ApiHost 10.0.0.241 -ApiName InVentry-PC
#>
[CmdletBinding()]
param(
    [string]$ApiHost = "10.0.0.241",
    [string]$ApiName = "InVentry-PC",
    [int]$Port = 4816,
    [string]$CertFile = "C:\SDIIntelligence\inventry.pem",
    [string]$EnvFile = "$PSScriptRoot\..\.env"
)

$ErrorActionPreference = "Stop"
$script:problems = @()

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Good($text) { Write-Host "   OK   $text" -ForegroundColor Green }
function Bad($text)  { Write-Host "   FAIL $text" -ForegroundColor Red; $script:problems += $text }
function Note($text) { Write-Host "        $text" -ForegroundColor DarkGray }

Step "1. Can this machine reach the InVentry API?"
# The API is on-premises only, so this must pass from the machine that will run
# the sync - not just from a desktop that happens to be on the same LAN.
$reach = Test-NetConnection -ComputerName $ApiHost -Port $Port -WarningAction SilentlyContinue
if ($reach.TcpTestSucceeded) {
    Good "$ApiHost`:$Port reachable from $($reach.SourceAddress.IPAddress)"
} else {
    Bad "$ApiHost`:$Port NOT reachable. Check firewall rules and routing from this host."
    Note "Nothing else here will work until this passes."
}

Step "2. Hosts entry for $ApiName"
$hostsFile = "$env:windir\System32\drivers\etc\hosts"
if (Select-String -Path $hostsFile -Pattern "\s$ApiName\s*$" -Quiet -ErrorAction SilentlyContinue) {
    Good "$ApiName already in the hosts file"
} else {
    try {
        Add-Content -Path $hostsFile -Value "$ApiHost   $ApiName"
        Good "Added: $ApiHost   $ApiName"
    } catch {
        Bad "Could not write to the hosts file - run this script as Administrator."
    }
}
$resolved = (Resolve-DnsName $ApiName -ErrorAction SilentlyContinue).IPAddress
if ($resolved -contains $ApiHost) {
    Good "$ApiName resolves to $ApiHost"
} else {
    Note "$ApiName does not resolve yet; if you just added it, re-run to confirm."
}

Step "3. Certificate"
if (Test-Path $CertFile) {
    Good "Already present at $CertFile"
} else {
    & "$PSScriptRoot\..\tools\get_inventry_cert.ps1" -ApiHost $ApiHost -Port $Port -OutFile $CertFile
    if (Test-Path $CertFile) { Good "Captured to $CertFile" } else { Bad "Certificate capture failed" }
}

Step "4. .env settings"
$resolvedEnv = Resolve-Path $EnvFile -ErrorAction SilentlyContinue
if (-not $resolvedEnv) {
    Bad "No .env found at $EnvFile. Copy it from a working machine - it is deliberately not in git."
} else {
    $envText = Get-Content $resolvedEnv
    foreach ($name in @("INVENTRY_API_BASE_URL", "INVENTRY_API_KEY", "INVENTRY_PARTNER_SECRET")) {
        $line = $envText | Where-Object { $_ -match "^$name=" }
        if (-not $line)                     { Bad  "$name is missing from .env" }
        elseif ($line -match "^$name=\s*$") { Bad  "$name is present but empty" }
        else                                { Good "$name is set" }
    }
    if (-not ($envText | Where-Object { $_ -match "^INVENTRY_API_CA_BUNDLE=\S" })) {
        Note "INVENTRY_API_CA_BUNDLE not set - TLS verification stays off unless it points at $CertFile"
    }
    # Their certificate is CN=InVentry-PC with no subjectAltName, which modern
    # TLS ignores, so no hostname ever matches. Pinning the certificate and
    # skipping the name check keeps the connection verified.
    if (-not ($envText | Where-Object { $_ -match "^INVENTRY_API_CHECK_HOSTNAME=(false|0|no|off)" })) {
        Bad "INVENTRY_API_CHECK_HOSTNAME is not set to false. InVentry's certificate has no subjectAltName, so verification fails with 'certificate is not valid for inventry-pc'."
        Note "Add: INVENTRY_API_CHECK_HOSTNAME=false   (keep INVENTRY_API_CA_BUNDLE set - the certificate is still checked)"
    }
}

Step "Result"
if ($script:problems.Count -eq 0) {
    Write-Host "Ready. Prove it with:" -ForegroundColor Green
    Write-Host "  python hr_onsite_push.py --check"
} else {
    Write-Host "$($script:problems.Count) problem(s) to fix:" -ForegroundColor Red
    $script:problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
