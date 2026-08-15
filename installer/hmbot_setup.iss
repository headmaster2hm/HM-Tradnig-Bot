; HM Bot Trader — Inno Setup installer script.
; Compile with: ISCC.exe installer\hmbot_setup.iss  (see build_installer.ps1)
;
; Expects dist\HMBotTrader\HMBotTrader.exe already built by PyInstaller
; (hmbot_trader.spec). User data (settings.json, trades.db, license.json)
; is written to %LOCALAPPDATA%\HMBotTrader at runtime, never to {app}.

#define MyAppName "HM Bot Trader"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "HM Bot Trader"
#define MyAppExeName "HMBotTrader.exe"
#define MyAppId "7C0E2F1B-9A4D-4B78-AC1D-2E5F6A3D8B14"

; Optional code signing of the uninstaller. Define SIGN_SETUP on the ISCC
; command line (e.g. /DSIGN_SETUP) and override the tool via /Shmbot_sign=...
; to enable; the build scripts do this when a signing thumbprint is present.

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName}
AppComments=Automated MetaTrader 5 dashboard
DefaultDirName={localappdata}\Programs\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=HMBotTrader-Setup
SetupIconFile=..\assets\icon.ico
WizardStyle=modern
WizardImageFile=..\assets\installer_welcome.png
Compression=lzma2
SolidCompression=yes
WizardSizePercent=100
ShowLanguageDialog=no
DisableWelcomePage=no
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartIfNeededByRun=no
#ifdef SIGN_SETUP
SignTool=hmbot_sign
SignedUninstaller=yes
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "autostart"; Description: "Launch {#MyAppName} after installation"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\HMBotTrader\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent; Tasks: autostart

; User data (settings.json, trades.db, license.json) stays in
; %LOCALAPPDATA%\HMBotTrader across uninstall/reinstall so a paid license
; key and trade history are never destroyed. Delete that folder manually
; to fully wipe local data.
