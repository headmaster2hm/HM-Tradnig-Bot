# Build the HM Bot Trader Windows installer (one command).
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\build_installer.ps1
#
# Produces: dist\HMBotTrader-Setup.exe  (send this ONE file to users)
#
# Requirements on THIS machine (the seller's PC):
#   - Windows 10/11
#   - Internet (Python, PyInstaller and Inno Setup are installed/verified
#     for you automatically the first time)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== HM Bot Trader installer build ==="

# --- Signing helpers ---------------------------------------------------
# Signs files when a thumbprint exists (installer\signing_thumbprint.txt).
# With the test cert from create_signing_cert.ps1 this validates the
# pipeline; replace that cert with a trusted-CA cert for real SmartScreen-safe
# releases.
$SigningThumbprintFile = Join-Path $PSScriptRoot "installer\signing_thumbprint.txt"
$SigningThumbprint = $null
if (Test-Path $SigningThumbprintFile) {
    $SigningThumbprint = (Get-Content $SigningThumbprintFile -Raw).Trim()
}

function Find-SignTool {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe",
        "${env:ProgramFiles}\Windows Kits\10\bin\*\x64\signtool.exe"
    )
    foreach ($candidate in $candidates) {
        $found = Get-ChildItem -Path $candidate -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
        if ($found) { return $found }
    }
    return $null
}

function Sign-File {
    param([string]$FilePath)
    if (-not $SigningThumbprint) {
        Write-Host "  (skipping signature: no installer\signing_thumbprint.txt)"
        return
    }
    if (-not $signtool) {
        Write-Host "  (skipping signature: signtool.exe not found)"
        return
    }
    if (-not (Test-Path $FilePath)) {
        Write-Host "  (skipping signature: $FilePath not found)"
        return
    }
    Write-Host "  Signing $FilePath"
    & $signtool sign /fd SHA256 `
        /tr http://timestamp.digicert.com /td SHA256 `
        /sha1 $SigningThumbprint /s my $FilePath
    if ($LASTEXITCODE -ne 0) { throw "Signing failed for $FilePath (exit code $LASTEXITCODE)" }
}

$signtool = Find-SignTool
if ($SigningThumbprint) {
    Write-Host "==> Code signing ENABLED (thumbprint $SigningThumbprint)"
    if (-not $signtool) { Write-Host "    WARNING: signtool.exe not found - files will NOT be signed" }
}

# --- 1. Python ---------------------------------------------------------
$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) {
    throw "Python not found. Install Python 3.12+ from python.org (tick 'Add python.exe to PATH'), then re-run."
}
python --version

# --- 2. Build tools -----------------------------------------------------
Write-Host "==> Ensuring build tools (pyinstaller)..."
python -m pip install -q --upgrade "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }

Write-Host "==> Ensuring runtime deps used by PyInstaller analysis..."
python -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }

# --- 3. PyInstaller (one-folder build) ----------------------------------
$distPath = Join-Path $PSScriptRoot "dist"
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $distPath "HMBotTrader")

Write-Host "==> Building HMBotTrader.exe (this can take a few minutes)..."
python -m PyInstaller --noconfirm --clean --distpath $distPath hmbot_trader.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exePath = Join-Path $distPath "HMBotTrader\HMBotTrader.exe"
if (-not (Test-Path $exePath)) {
    throw "Build failed: $exePath not found"
}

# --- 3b. Sign the app executable ----------------------------------------
Write-Host "==> Signing HMBotTrader.exe..."
Sign-File -FilePath $exePath

# --- 4. Inno Setup ------------------------------------------------------
function Find-ISCC {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe",
        "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}
$iscc = Find-ISCC
if (-not $iscc) {
    Write-Host "==> Inno Setup not found - installing it now (one time)..."
    winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup install failed - re-run after installing manually" }
    $iscc = Find-ISCC
    if (-not $iscc) { throw "Inno Setup was installed but ISCC.exe was not found" }
}

Write-Host "==> Compiling installer..."
if ($SigningThumbprint -and $signtool) {
    $signCmd = '$q{0}$q sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /sha1 {1} /s my $q$f$q' -f $signtool, $SigningThumbprint
    & $iscc "/DSIGN_SETUP" "/Shmbot_sign=$signCmd" "installer\hmbot_setup.iss"
}
else {
    & $iscc "installer\hmbot_setup.iss"
}
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed with exit code $LASTEXITCODE" }

$setupPath = Join-Path $distPath "HMBotTrader-Setup.exe"

# --- 5. Sign the installer ----------------------------------------------
Write-Host "==> Signing installer..."
Sign-File -FilePath $setupPath

Write-Host ""
Write-Host "========================================================"
Write-Host "  DONE. Your installer is ready:"
Write-Host ""
Write-Host "    $setupPath"
if ($SigningThumbprint) {
    Write-Host ""
    Write-Host "  Signed with thumbprint: $SigningThumbprint"
    Write-Host "  Verify with: signtool verify /pa /v `"$setupPath`""
}
Write-Host ""
Write-Host "  Send that ONE file to your users. They run it, get"
Write-Host "  Start-menu + desktop shortcuts and an uninstaller."
Write-Host "  No Python needed on their side."
Write-Host "========================================================"
