; Script generated for ShortBot Windows Desktop Companion Installer
; Inno Setup 6+ script

#define MyAppName "ShortBot Engine"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ShortBot"
#define MyAppURL "https://github.com/bigmanrohan12/ShortBot"
#define MyAppExeName "ShortBot-Engine.exe"

[Setup]
AppId={{8B29C5B2-749C-4B6A-91A9-F2EB28749D01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={localappdata}\ShortBot
DisableProgramGroupPage=yes
OutputBaseFilename=ShortBot-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=dist

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\ShortBot-Engine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; Mozilla Firefox Native Messaging Host Registration
Root: HKCU; Subkey: "Software\Mozilla\NativeMessagingHosts\com.shortbot.backend"; ValueType: string; ValueData: "{app}\com.shortbot.backend.firefox.json"; Flags: uninsdeletekey

; Google Chrome & Microsoft Edge Native Messaging Host Registration
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.shortbot.backend"; ValueType: string; ValueData: "{app}\com.shortbot.backend.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.shortbot.backend"; ValueType: string; ValueData: "{app}\com.shortbot.backend.json"; Flags: uninsdeletekey

[Run]
Filename: "{app}\Install-ShortBot.bat"; Flags: runhidden
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
