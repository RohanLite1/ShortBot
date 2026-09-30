; Script generated for ShortBot Windows Desktop Companion Installer
; Inno Setup 6+ script - 100% Native, No Batch Scripts Required

#define MyAppName "ShortBot Companion Engine"
#define MyAppVersion "1.1.1"
#define MyAppPublisher "ShortBot"
#define MyAppURL "https://github.com/bigmanrohan12/ShortBot"
#define MyAppExeName "ShortBot-Engine.exe"

#ifndef MyAppFlavor
  #define MyAppFlavor "Full"
#endif

#if MyAppFlavor == "Lite"
  #define MyOutputBaseFilename "ShortBot-Setup-Lite"
#else
  #define MyOutputBaseFilename "ShortBot-Setup"
#endif

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
OutputBaseFilename={#MyOutputBaseFilename}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir=dist
UninstallDisplayIcon={app}\{#MyAppExeName}
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "startwithwindows"; Description: "&Start ShortBot Companion Engine automatically when Windows boots"; Flags: checkedonce
Name: "desktopicon"; Description: "Create a &desktop shortcut for ShortBot Engine"; Flags: unchecked

[Files]
#if MyAppFlavor == "Lite"
Source: "dist\ShortBot-Engine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bat,*.log,downloads\*,*.mp4,*.mkv,*.webm,*.part,*.ytdl,bin\*"
#else
Source: "dist\ShortBot-Engine\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.bat,*.log,downloads\*,*.mp4,*.mkv,*.webm,*.part,*.ytdl"
#endif

[Icons]
Name: "{autoprograms}\ShortBot Companion Engine"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\Uninstall ShortBot Companion Engine"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ShortBot Companion Engine"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\ShortBot Engine"; Filename: "{app}\{#MyAppExeName}"; Tasks: startwithwindows

[Registry]
; Mozilla Firefox Native Messaging Host Registration
Root: HKCU; Subkey: "Software\Mozilla\NativeMessagingHosts\com.shortbot.backend"; ValueType: string; ValueData: "{app}\com.shortbot.backend.firefox.json"; Flags: uninsdeletekey

; Google Chrome & Microsoft Edge Native Messaging Host Registration
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.shortbot.backend"; ValueType: string; ValueData: "{app}\com.shortbot.backend.json"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.shortbot.backend"; ValueType: string; ValueData: "{app}\com.shortbot.backend.json"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName} in background"; Flags: nowait postinstall skipifsilent

[Code]
// Dynamically write Firefox and Chrome/Edge native messaging JSON manifests on install
procedure CurStepChanged(CurStep: TSetupStep);
var
  AppDir, HostExePath, EscapedHostPath, JsonFirefox, JsonChrome: String;
begin
  if CurStep = ssPostInstall then
  begin
    AppDir := ExpandConstant('{app}');
    HostExePath := AppDir + '\native_host.exe';
    EscapedHostPath := HostExePath;
    StringChangeEx(EscapedHostPath, '\', '\\', True);

    // 1. Firefox manifest
    JsonFirefox := '{"name":"com.shortbot.backend","description":"ShortBot Native Messaging Host","path":"' + EscapedHostPath + '","type":"stdio","allowed_extensions":["shortbot@curator.app"]}';
    SaveStringToFile(AppDir + '\com.shortbot.backend.firefox.json', JsonFirefox, False);

    // 2. Chrome & Edge manifest
    JsonChrome := '{"name":"com.shortbot.backend","description":"ShortBot Native Messaging Host","path":"' + EscapedHostPath + '","type":"stdio","allowed_origins":["chrome-extension://gfoaiibpnmjdgkkfpbkdgodljmepondo/","extension://gfoaiibpnmjdgkkfpbkdgodljmepondo/"]}';
    SaveStringToFile(AppDir + '\com.shortbot.backend.json', JsonChrome, False);
  end;
end;

// On uninstall, ensure running processes are cleanly terminated
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('taskkill.exe', '/F /IM ShortBot-Engine.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM shortbot-engine.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    Exec('taskkill.exe', '/F /IM native_host.exe /T', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
