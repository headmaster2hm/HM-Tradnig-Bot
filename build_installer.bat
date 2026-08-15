@echo off
REM ============================================================
REM  HM Bot Trader - Windows installer build (one command)
REM  Produces: dist\HMBotTrader-Setup.exe
REM
REM  Requirements on THIS machine (the seller's PC):
REM    - Windows 10/11
REM    - Internet (PyInstaller and Inno Setup are installed for
REM      you automatically the first time via winget)
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"
title HM Bot Trader - Windows installer build

echo.
echo === HM Bot Trader build ===
echo.

where python >nul 2>nul
if errorlevel 1 goto :python_fail
python --version
if errorlevel 1 goto :fail

echo Installing build tools (first run downloads packages)...
python -m pip install -q --upgrade "pyinstaller>=6.0"
if errorlevel 1 goto :fail
python -m pip install -q -r requirements.txt
if errorlevel 1 goto :fail

if exist "dist\HMBotTrader" rmdir /s /q "dist\HMBotTrader"

echo Building HMBotTrader.exe (takes a few minutes)...
python -m PyInstaller --noconfirm --clean --distpath dist hmbot_trader.spec
if errorlevel 1 goto :fail
if not exist "dist\HMBotTrader\HMBotTrader.exe" goto :fail

REM ---- Code signing setup (test cert from create_signing_cert.ps1) ----
set "SIGN_THUMBPRINT="
if exist "installer\signing_thumbprint.txt" set /p SIGN_THUMBPRINT=<"installer\signing_thumbprint.txt"
set "SIGNTOOL="
for /d %%d in ("C:\Program Files (x86)\Windows Kits\10\bin\*") do (
    if exist "%%d\x64\signtool.exe" if not defined SIGNTOOL set "SIGNTOOL=%%d\x64\signtool.exe"
)
if not defined SIGNTOOL for /d %%d in ("C:\Program Files\Windows Kits\10\bin\*") do (
    if exist "%%d\x64\signtool.exe" if not defined SIGNTOOL set "SIGNTOOL=%%d\x64\signtool.exe"
)
if defined SIGN_THUMBPRINT (
    echo ==^> Code signing ENABLED ^(thumbprint %SIGN_THUMBPRINT%^)
    if not defined SIGNTOOL echo     WARNING: signtool.exe not found - files will NOT be signed
) else (
    echo ==^> No signing_thumbprint.txt found - files will NOT be signed.
    echo     Run: powershell -ExecutionPolicy Bypass -File .\installer\create_signing_cert.ps1
)

echo Signing HMBotTrader.exe...
call :sign_file "dist\HMBotTrader\HMBotTrader.exe"
if errorlevel 1 goto :fail

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC goto :install_inno
goto :inno_ok

:install_inno
echo Inno Setup not found - installing it now (one time)...
winget install -e --id JRSoftware.InnoSetup --silent --accept-package-agreements --accept-source-agreements
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC goto :inno_fail

:inno_ok
echo Compiling installer...
set "SIGNCMD=$q%SIGNTOOL%$q sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /sha1 %SIGN_THUMBPRINT% /s my $q$f$q"
if defined SIGN_THUMBPRINT if defined SIGNTOOL (
    "%ISCC%" /DSIGN_SETUP "/Shmbot_sign=%SIGNCMD%" installer\hmbot_setup.iss
) else (
    "%ISCC%" installer\hmbot_setup.iss
)
if errorlevel 1 goto :fail

echo Signing installer...
call :sign_file "dist\HMBotTrader-Setup.exe"
if errorlevel 1 goto :fail

echo.
echo ==================================================================
echo   DONE. Your installer is ready:
echo.
echo     dist\HMBotTrader-Setup.exe
echo.
if defined SIGN_THUMBPRINT (
echo   Signed with thumbprint: %SIGN_THUMBPRINT%
echo   Verify with: signtool verify /pa /v dist\HMBotTrader-Setup.exe
echo.
)
echo   Send that ONE file to your users. They run it, get
echo   Start-menu + desktop shortcuts and an uninstaller.
echo   No Python needed on their side.
echo ==================================================================
pause
exit /b 0

:sign_file
if not defined SIGN_THUMBPRINT (echo   ^(skipping signature: no thumbprint^) & exit /b 0)
if not defined SIGNTOOL (echo   ^(skipping signature: signtool not found^) & exit /b 0)
if not exist "%~1" (echo   ^(skipping signature: %~1 not found^) & exit /b 0)
echo   Signing %~1
"%SIGNTOOL%" sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /sha1 %SIGN_THUMBPRINT% /s my "%~1"
exit /b %errorlevel%

:python_fail
echo.
echo Python not found. Install Python 3.12+ from python.org
echo and tick "Add python.exe to PATH", then run this script again.
goto :fail

:inno_fail
echo.
echo Inno Setup install FAILED - re-run this script after installing it manually.
goto :fail

:fail
echo.
echo BUILD FAILED. See messages above.
pause
exit /b 1
