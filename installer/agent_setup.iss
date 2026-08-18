; HM Bridge Agent — Inno Setup installer script.
; Compile with: ISCC.exe installer\agent_setup.iss  (see build_win.bat)
;
; Expects dist\HM_Bridge_Agent.exe already built by PyInstaller (agent_app.spec).

#define MyAppName "HM Bridge Agent"
#define MyAppVersion "1.1.0"
#define MyAppPublisher "HM Bot Trader"
#define MyAppExeName "HM_Bridge_Agent.exe"
#define MyAppId "0B7C2E9F-4A6D-4E88-BC1D-9F3A5E7B2C14"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppVerName={#MyAppName}
DefaultDirName={autopf}\{#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=HMBotBridgeAgent-Setup
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

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "autostart"; Description: "Run {#MyAppName} automatically when you sign in to &Windows"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Auto-start with Windows when the user chose the task.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; \
  ValueName: "HMBotBridgeAgent"; ValueData: """{app}\{#MyAppExeName}"" --autostart"; \
  Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} now"; \
  Flags: nowait postinstall skipifsilent
