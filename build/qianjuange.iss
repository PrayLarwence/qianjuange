; ============================================================
; 千卷阁 (Qianjuange) Inno Setup 安装脚本
;
; 使用 ISCC 编译:
;   "C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe" build\qianjuange.iss
; 或直接用 build\build-installer.bat
;
; 前置: build\dist\Qianjuange\ 已经由 PyInstaller 构建好.
;       中文语言包 ChineseSimplified.isl 已放入 Inno Setup 的 Languages\.
; ============================================================

#define AppName        "Qianjuange"
#define AppDisplayName "千卷阁"
#define AppVersion     "0.1.1"
#define AppPublisher   "Larwance"
#define AppExeName     "Qianjuange.exe"
#define SrcDir         "..\build\dist\Qianjuange"
#define IconFile       "..\build\assets\icon.ico"

[Setup]
; AppId: 唯一标识, 升级 / 卸载靠这个匹配, *绝对不要*改.
AppId={{A7C9F2E1-3B5D-4F8A-9C6E-2D1B7E4A8F39}}

AppName={#AppDisplayName}
AppVersion={#AppVersion}
AppVerName={#AppDisplayName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}

; 用户目录安装: 不需要管理员权限
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppDisplayName}
DisableDirPage=no
DisableProgramGroupPage=yes

; 输出
OutputDir=..\build\installer
OutputBaseFilename=Qianjuange-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes

; 外观
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppDisplayName}
WizardStyle=modern
WizardSizePercent=110
ShowLanguageDialog=no

; 兼容性
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763

; 卸载时关闭运行中实例
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller 产物整目录拷过去
Source: "{#SrcDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcDir}\_internal\*"; DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppDisplayName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\卸载 {#AppDisplayName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{#AppDisplayName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即启动 {#AppDisplayName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; pywebview / WebView2 在 {app} 下产生的运行时缓存 (cookies, cache, EBWebView)
; — 卸载时显式清掉, 否则 {app} 目录非空, Inno Setup 不会自动删父目录.
Type: filesandordirs; Name: "{app}\EBWebView"

[Code]
{ ----------- 卸载时询问是否清理用户数据 (%APPDATA%\Qianjuange) ----------- }

function GetUserDataDir(Param: String): String;
begin
  Result := ExpandConstant('{userappdata}\Qianjuange');
end;

procedure DeleteUserDataIfRequested;
var
  DataDir: String;
  Reply: Integer;
begin
  DataDir := GetUserDataDir('');
  if not DirExists(DataDir) then
    Exit;

  Reply := MsgBox(
    '检测到 千卷阁 的用户数据目录:' + #13#10 +
    DataDir + #13#10 + #13#10 +
    '这里包含你创建的世界库、章节、API key 等。' + #13#10 + #13#10 +
    '是否同时删除这些数据？' + #13#10 +
    '（选 "否" 会保留，下次重装可继续使用）',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2);

  if Reply = IDYES then
  begin
    if DelTree(DataDir, True, True, True) then
      MsgBox('用户数据已删除。', mbInformation, MB_OK)
    else
      MsgBox('用户数据删除失败，可手动清理:' + #13#10 + DataDir,
             mbError, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    DeleteUserDataIfRequested;
end;
