#define AppName "MIDI2KEY for Genshin"
#define AppVersion "1.0.0"
#define AppExeName "MIDI2KEY-for-Genshin.exe"

[Setup]
AppId={{B341CFB9-1216-43BA-AE16-8AF7F9321382}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Oceannn233
AppPublisherURL=https://github.com/Oceannn233/MIDI2KEY-for-Genshin
AppSupportURL=https://github.com/Oceannn233/MIDI2KEY-for-Genshin/issues
DefaultDirName={localappdata}\Programs\MIDI2KEY-for-Genshin
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\release\windows
OutputBaseFilename=MIDI2KEY-for-Genshin-Setup-v{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
SetupIconFile=..\..\assets\app-icon.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\release\windows\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
