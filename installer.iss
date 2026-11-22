; 视频转图片/动图工具 安装包脚本
; Inno Setup 6
; PrivilegesRequired=lowest：免管理员权限安装（全程无 UAC 弹窗），装到用户级 Program Files
[Setup]
LicenseFile=LICENSE
RedirectionGuard=no
AppId={{3E7A1F42-8C9D-4B65-9A0E-D2F8B6C45E10}
AppName=视频转图片/动图工具
AppVersion=2.6
AppPublisher=深圳市创炫互动网络科技有限公司
AppPublisherURL=https://www.mrheedu.com
AppSupportURL=https://www.mrheedu.com
AppUpdatesURL=https://www.mrheedu.com
DefaultDirName={autopf}\视频转图片工具
DefaultGroupName=视频转图片工具
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\视频转图片.exe
UninstallDisplayName=视频转图片/动图工具
SetupIconFile=图标.ico
OutputDir=installer_output
OutputBaseFilename=视频转图片工具_安装包_v2.6
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: checkedonce

[Files]
Source: "dist\视频转图片\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[Icons]
Name: "{group}\视频转图片工具"; Filename: "{app}\视频转图片.exe"; IconFilename: "{app}\视频转图片.exe"
Name: "{group}\卸载视频转图片工具"; Filename: "{uninstallexe}"
Name: "{autodesktop}\视频转图片工具"; Filename: "{app}\视频转图片.exe"; IconFilename: "{app}\视频转图片.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\视频转图片.exe"; Description: "立即启动视频转图片工具"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; 卸载时删除用户数据（可选，暂不删除）
