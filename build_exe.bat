@echo off
REM Build a shareable Windows folder for HM Bot Trader (no source code).
setlocal
cd /d "%~dp0"

echo === HM Bot Trader build ===

pip install -q "pyinstaller>=6.0"
if errorlevel 1 (
  echo PIP INSTALL FAILED
  exit /b 1
)

if exist build rmdir /s /q build
if exist "dist\HMBotTrader" rmdir /s /q "dist\HMBotTrader"
if exist "dist\HMBotTrader.zip" del /f /q "dist\HMBotTrader.zip"

python -m PyInstaller --noconfirm --clean ^
  --distpath dist --workpath build ^
  --name HMBotTrader ^
  --add-data "config\settings.dist.json;config" ^
  --add-data "dashboard\web;dashboard\web" ^
  --collect-all MetaTrader5 ^
  main.py
if errorlevel 1 (
  echo BUILD FAILED
  exit /b 1
)

if not exist "dist\HMBotTrader\HMBotTrader.exe" (
  echo HMBotTrader.exe not found
  exit /b 1
)

copy /y config\settings.dist.json "dist\HMBotTrader\settings.json" >nul

powershell -Command "Compress-Archive -Path 'dist\HMBotTrader' -DestinationPath 'dist\HMBotTrader.zip' -Force"

echo.
echo Done. Folder: dist\HMBotTrader   Zip: dist\HMBotTrader.zip
endlocal
