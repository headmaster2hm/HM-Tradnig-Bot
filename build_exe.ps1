# Build a shareable Windows folder for HM Bot Trader (no source code).
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File .\build_exe.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Ensuring build tools (pyinstaller)..."
python -m pip install -q "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

$distPath = Join-Path $PSScriptRoot "dist"
$workPath = Join-Path $PSScriptRoot "build"
New-Item -ItemType Directory -Force -Path $distPath, $workPath | Out-Null
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $distPath "HMBotTrader")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $workPath "*")
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $distPath "HMBotTrader.zip")

Write-Host "==> Building HMBotTrader.exe (this can take a few minutes)..."
python -m PyInstaller --noconfirm --clean --distpath $distPath --workpath $workPath hmbot_trader.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$distDir = Join-Path $distPath "HMBotTrader"
$exePath = Join-Path $distDir "HMBotTrader.exe"
if (-not (Test-Path $exePath)) {
    throw "Build failed: HMBotTrader.exe not found in $distDir"
}

# Seed a clean settings file next to the exe (no credentials).
Copy-Item .\config\settings.dist.json (Join-Path $distDir "settings.json") -Force

@"
HM Bot Trader
=============

What you need:
- Windows PC
- MetaTrader 5 installed (for live trading)
- Your own broker login (do not use someone else's account)

How to start:
1. Open MetaTrader 5 and log in.
2. Turn on Algo Trading.
3. Double-click HMBotTrader.exe - your browser opens the dashboard
   at http://127.0.0.1:PORT
4. The first time you open it you must activate the bot with your
   license key (one-time fee). Enter the key you received by email.
5. Keep dry_run / paper mode on until you are comfortable.
6. Open Settings in the app to set symbol, lot size, and MT5 details.

Notes:
- The dashboard runs on your local machine only (127.0.0.1).
- logs\ and trades.db are created automatically.
- Do not delete the _internal folder - the app needs it.
"@ | Set-Content -Encoding UTF8 (Join-Path $distDir "README.txt")

$zipPath = Join-Path $distPath "HMBotTrader.zip"
Write-Host "==> Creating zip for sharing..."
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $distDir -DestinationPath $zipPath -Force

Write-Host ""
Write-Host "Done."
Write-Host "  Folder: $distDir"
Write-Host "  Zip:    $zipPath"
Write-Host "Send the zip. Recipient should unzip and run HMBotTrader.exe"
