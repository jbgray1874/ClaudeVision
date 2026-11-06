<#
.SYNOPSIS
    Export the InVentry Partner API certificate from the TLS handshake.

.DESCRIPTION
    InVentry's certificate is self-signed and normally fetched from the V4
    folder on the main unit. That needs share credentials, which we do not
    currently have, so this takes the certificate straight off the wire
    instead - it is the same certificate, and only the public half.

    Prints the Subject, which matters: the certificate is issued to a machine
    name, so connecting by IP fails hostname verification even with the
    certificate trusted. See docs/INVENTRY_API_NOTES.md.

.EXAMPLE
    .\get_inventry_cert.ps1
    .\get_inventry_cert.ps1 -ApiHost 10.0.0.241 -OutFile C:\SDIIntelligence\inventry.pem
#>
[CmdletBinding()]
param(
    [string]$ApiHost = "10.0.0.241",
    [int]$Port = 4816,
    [string]$OutFile = "C:\SDIIntelligence\inventry.pem"
)

$ErrorActionPreference = "Stop"
$previous = [Net.ServicePointManager]::ServerCertificateValidationCallback
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    # We are fetching the certificate in order to trust it, so validation has
    # to be off for this one call.
    [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

    $url = "https://${ApiHost}:${Port}/PartnerAPI/CheckAuth"
    $req = [Net.HttpWebRequest]::Create($url)
    $req.Timeout = 15000
    try { $req.GetResponse() | Out-Null } catch { }   # 401 is fine; we only want the cert
    $cert = $req.ServicePoint.Certificate
    if (-not $cert) { throw "No certificate returned by $url - is the API listening?" }

    $x509 = New-Object Security.Cryptography.X509Certificates.X509Certificate2($cert)
    Write-Host "Subject : $($x509.Subject)"
    Write-Host "Issuer  : $($x509.Issuer)"
    Write-Host "Expires : $($x509.GetExpirationDateString())"
    Write-Host "Thumbprint: $($x509.Thumbprint)"

    $san = $x509.Extensions | Where-Object { $_.Oid.Value -eq "2.5.29.17" }
    if ($san) {
        Write-Host "SAN     : $($san.Format($false))"
        Write-Host "  -> hostname verification uses the SAN, not the CN."
    } else {
        Write-Host "SAN     : none"
        Write-Host "  -> no subjectAltName, so OpenSSL falls back to the CN above."
        Write-Host "     Connect using that name (hosts entry if DNS does not resolve it)"
        Write-Host "     or set INVENTRY_API_VERIFY=false."
    }

    $pem = "-----BEGIN CERTIFICATE-----`n" +
           [Convert]::ToBase64String($x509.Export('Cert'), 'InsertLineBreaks') +
           "`n-----END CERTIFICATE-----"
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null
    Set-Content -Path $OutFile -Value $pem -Encoding ascii
    Write-Host ""
    Write-Host "Saved to $OutFile" -ForegroundColor Green
    Write-Host "Set INVENTRY_API_CA_BUNDLE=$OutFile in .env"
}
finally {
    [Net.ServicePointManager]::ServerCertificateValidationCallback = $previous
}
