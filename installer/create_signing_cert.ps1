# Create a self-signed CodeSigning certificate for testing the signing pipeline.
#
# IMPORTANT: This is for TESTING ONLY. Windows SmartScreen will still warn
# end users on other machines. To remove the warning for real, replace this
# with a certificate from a trusted CA (Azure Trusted Signing, or an OV/EV
# cert from DigiCert/Sectigo/GlobalSign). This script just validates that
# signtool + timestamping + the build scripts work before you spend money.
#
# Creates / reuses a cert in the CurrentUser\My store and writes its
# thumbprint to installer\signing_thumbprint.txt, which the build scripts
# read to sign HMBotTrader.exe and HMBotTrader-Setup.exe.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\installer\create_signing_cert.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$CertSubject = "CN=HM Bot Trader (Test Signing)"
$ThumbprintFile = Join-Path $PSScriptRoot "signing_thumbprint.txt"

$existing = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert -ErrorAction SilentlyContinue |
    Where-Object { $_.Subject -eq $CertSubject } |
    Sort-Object NotAfter -Descending | Select-Object -First 1

if ($existing) {
    Write-Host "Using existing test certificate: $($existing.Subject) (expires $($existing.NotAfter))"
    $thumbprint = $existing.Thumbprint
}
else {
    Write-Host "==> Creating self-signed CodeSigning certificate..."
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $CertSubject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -KeyExportPolicy Exportable `
        -NotAfter (Get-Date).AddYears(3)
    $thumbprint = $cert.Thumbprint
    Write-Host "Created certificate thumbprint: $thumbprint"
}

Set-Content -Path $ThumbprintFile -Value $thumbprint -NoNewline
Write-Host ""
Write-Host "Thumbprint saved to: $ThumbprintFile"
Write-Host ""
Write-Host "Next step: run the installer build, then check the signature with:"
Write-Host "  signtool verify /pa /v dist\HMBotTrader-Setup.exe"
