#ifndef AppVersion
  #error AppVersion required
#endif
[Setup]
AppId={{0C1893D8-36AD-4981-8949-8E5FDF90BA63}
AppName=BC2.uplay2.ru Launcher
AppVersion={#AppVersion}
AppPublisher=BC2.uplay2.ru
AppPublisherURL=https://bc2.uplay2.ru/
DefaultDirName={localappdata}\Programs\BC2Launcher
DefaultGroupName=BC2.uplay2.ru
PrivilegesRequired=lowest
MinVersion=10.0
ArchitecturesAllowed=x64compatible
DisableProgramGroupPage=yes
OutputBaseFilename=BC2Launcher-Setup
SetupIconFile=..\launcher\assets\brand.ico
UninstallDisplayIcon={app}\BC2Launcher.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"

[Files]
Source: "{#SeedRoot}\BC2Launcher.exe"; DestName: "BC2Launcher-check.exe"; Flags: dontcopy
Source: "{#SeedRoot}\BC2Launcher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SeedRoot}\installation.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "{#SeedRoot}\seed-policy.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SeedRoot}\versions\*"; DestDir: "{app}\versions"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\BC2 Launcher"; Filename: "{app}\BC2Launcher.exe"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{group}\BC2 Launcher"; Filename: "{app}\BC2Launcher.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\BC2Launcher.exe"; Description: "Запустить BC2 Launcher"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\active.json"
Type: files; Name: "{app}\previous.json"
Type: files; Name: "{app}\activation.json"
Type: files; Name: "{app}\launcher-policy.json"
Type: files; Name: "{app}\update-state.json"
Type: files; Name: "{app}\client.lock"
Type: files; Name: "{app}\update.lock"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Code: Integer; Args: String;
begin
  Result := '';
  ExtractTemporaryFile('BC2Launcher-check.exe');
  Args := '--check-destination "' + ExpandConstant('{app}') + '" --seed-version {#AppVersion} --seed-inventory {#SeedInventory} --quiet';
  if not Exec(ExpandConstant('{tmp}\BC2Launcher-check.exe'), Args, '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    Result := 'Закройте лаунчер. Выберите пустую папку или прежнюю папку BC2 Launcher. Устанавливать лаунчер в папку игры нельзя.';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer;
begin
  if CurStep = ssPostInstall then
    if not Exec(ExpandConstant('{app}\BC2Launcher.exe'), '--install-seed {#AppVersion} --quiet', '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
      RaiseException('Не удалось проверить установленную версию. Повторите установку, закрыв лаунчер.');
end;

function InitializeUninstall(): Boolean;
var Code: Integer;
begin
  Result := Exec(ExpandConstant('{app}\BC2Launcher.exe'), '--uninstall-data --quiet', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  if not Result then
    SuppressibleMsgBox('Закройте лаунчер и повторите удаление. Настройки игры сохраняются.', mbError, MB_OK, IDOK);
end;
