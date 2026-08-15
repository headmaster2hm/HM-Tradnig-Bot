@echo off
REM ============================================================
REM  HM Bridge Agent - Windows installer build (one command)
REM  Produces: dist\HMBotBridgeAgent-Setup.exe
REM
REM  Requirements on THIS machine (the seller's PC):
REM    - Windows 10/11
REM    - Internet (Python and Inno Setup are installed for you
REM      automatically the first time via winget)
REM
REM  Optional: set HM_BRIDGE_URL / HM_BRIDGE_TOKEN before running
REM  to bake a different server link into the installer.
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title HM Bridge Agent - Windows installer build

echo.
echo === HM Bridge Agent build ===
echo.

where python >nul 2>nul
if errorlevel 1 goto :install_python
goto :python_ok

:install_python
echo Python not found - installing it now (one time)...
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :python_fail
where python >nul 2>nul
if errorlevel 1 goto :path_fail
echo Python installed.
goto :python_ok

:python_fail
echo.
echo Python install FAILED. Install Python 3.12 manually from python.org
echo and tick "Add python.exe to PATH", then run this script again.
goto :fail

:path_fail
echo.
echo Python was installed but PATH is not updated yet.
echo Close this window and run build_win.bat again.
goto :fail

:python_ok
python --version
if errorlevel 1 goto :fail

echo Installing build tools (first run downloads ~100 MB)...
python -m pip install -q --upgrade pyinstaller pillow MetaTrader5 websocket-client numpy
if errorlevel 1 goto :fail

if defined HM_BRIDGE_URL goto :bake
if defined HM_BRIDGE_TOKEN goto :bake
goto :no_bake

:bake
echo Baking server url/token into the build...
python installer\bake_defaults.py
if errorlevel 1 goto :fail

:no_bake
echo Building HM_Bridge_Agent.exe (takes a few minutes)...
python -m PyInstaller --noconfirm --clean agent_app.spec
if errorlevel 1 goto :fail
if not exist "dist\HM_Bridge_Agent.exe" goto :fail

set "ISCC="
call :find_iscc
if defined ISCC goto :inno_ok

:install_inno
echo Inno Setup not found - installing it now (one time)...
winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
call :find_iscc
if not defined ISCC goto :inno_fail

:inno_ok
echo Compiling installer...
"%ISCC%" installer\agent_setup.iss
if errorlevel 1 goto :fail

echo.
echo ==================================================================
echo   DONE. Your installer is ready:
echo.
echo     dist\HMBotBridgeAgent-Setup.exe
echo.
echo   Send that ONE file to your users. They run it, it finds their
echo   MetaTrader 5, and connects - no Python needed on their side.
echo ==================================================================
pause
exit /b 0

:inno_fail
echo.
echo Inno Setup install FAILED. It was not found in any of these locations:
echo   %ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
echo   %ProgramFiles%\Inno Setup 6\ISCC.exe
echo   %LocalAppData%\Programs\Inno Setup 6\ISCC.exe
echo   %LocalAppData%\Programs\Inno Setup\ISCC.exe
echo Install Inno Setup 6 manually from https://jrsoftware.org/isinfo.php
echo then re-run this script.
goto :fail

:find_iscc
if defined ISCC goto :eof
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if defined ISCC goto :eof
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if defined ISCC goto :eof
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if defined ISCC goto :eof
if exist "%LocalAppData%\Programs\Inno Setup\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup\ISCC.exe"
goto :eof

:fail
echo.
echo BUILD FAILED. See messages above.
pause
exit /b 1
