; Instalador Inno Setup — AgenteBc Worker (portal de registro en lote).
; Compilar tras: scripts\build-worker.ps1

#define MyAppName "AgenteBc Worker"
#define MyAppVersion "0.2.9"
#define MyAppPublisher "Malla Publicidad"
#define MyAppURL "https://agentebc.malla.es"
#define MyAppExeName "AgenteBcWorker.exe"

[Setup]
AppId={{B2C3D4E5-F6A7-8901-BCDE-F12345678901}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases/worker-latest.json
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputBaseFilename=AgenteBcWorker-{#MyAppVersion}-setup
OutputDir=Output
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=agentebc.ico
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "agentebc.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\AgenteBcWorker.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\agentebc.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\agentebc.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent
