#define MyAppName "Miaobi Studio"
#define MyAppVersion "0.1.1"
#define MyAppExeName "Miaobi.exe"

[Setup]
AppId={{1D747B03-280A-4B41-BF36-792F9A3A49D4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Miaobi Studio
AppPublisherURL=https://github.com/xiaoyoumi9924/handwritten-notes
DefaultDirName={localappdata}\Programs\Miaobi
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist-installer
OutputBaseFilename=Miaobi-Setup-Windows
SetupIconFile=miaobi.ico
UninstallDisplayIcon={app}\Miaobi.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Files]
Source: "..\dist\Miaobi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Miaobi Studio"; Filename: "{app}\Miaobi.exe"; IconFilename: "{app}\Miaobi.exe"
Name: "{autodesktop}\Miaobi Studio"; Filename: "{app}\Miaobi.exe"; IconFilename: "{app}\Miaobi.exe"

[Run]
Filename: "{app}\Miaobi.exe"; Description: "Launch Miaobi Studio"; Flags: nowait postinstall skipifsilent
