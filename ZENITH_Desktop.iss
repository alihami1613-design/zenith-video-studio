[Setup]
AppId={{B7D8F21A-6D3B-4C7A-9A6E-4D8B1A2C5F70}
AppName=ZENITH Desktop
AppVersion=0.1.0
AppPublisher=ZENITH
DefaultDirName={autopf}\ZENITH Desktop
DefaultGroupName=ZENITH Desktop
UninstallDisplayIcon={app}\ZENITH Desktop.exe
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
OutputDir=dist-installer
OutputBaseFilename=ZENITH-Desktop-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\ZENITH Desktop\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ZENITH Desktop"; Filename: "{app}\ZENITH Desktop.exe"
Name: "{autodesktop}\ZENITH Desktop"; Filename: "{app}\ZENITH Desktop.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\ZENITH Desktop.exe"; Description: "Launch ZENITH Desktop"; Flags: postinstall nowait skipifsilent
