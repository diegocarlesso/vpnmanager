; Script do Inno Setup para o VPN Manager.
;
; IMPORTANTE: AppVersion abaixo deve ser mantido em sincronia manual com
; APP_VERSION em utils/constants.py (a única fonte de verdade em runtime,
; exibida no título da janela). Não há build step automático ligando os dois.
;
; Gera um instalador que grava em Program Files (modo "instalado"), cria um
; marcador installed.marker lido por utils/constants.py para mover config/logs
; para %LOCALAPPDATA%\VPNManager (ver _installed_mode_requested() e
; migrate_portable_settings_if_needed()). Sem assinatura de código — isso
; requer um certificado Authenticode da organização, fora do escopo deste script.
;
; Para compilar (com o Inno Setup 6 já instalado neste ambiente):
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\vpnmanager.iss

#define MyAppName "VPN Manager"
#define MyAppVersion "1.2.1"
#define MyAppPublisher "VPNManager"
#define MyAppExeName "VPNManager.exe"

[Setup]
AppId={{B6E6C6B0-9B6B-4B7C-9B0B-VPNMANAGER01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\VPNManager
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=VPNManagerSetup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
; Program Files exige privilégio de administrador para instalar/desinstalar.
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
; Sem assinatura de código (Authenticode) — ver nota no topo do arquivo.

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked

[Files]
Source: "..\dist\VPNManager.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; O marcador de "modo instalado" não é removido automaticamente pelo Inno
; (não está em [Files]); precisa ser apagado explicitamente na desinstalação.
Type: files; Name: "{app}\installed.marker"

[Registry]
; Remove a entrada de "iniciar com o Windows" (gravada pelo próprio app em
; SettingsManager.apply_startup_registration) na desinstalação — sem isso, o
; Run key ficaria apontando para um .exe que não existe mais.
;
; LIMITAÇÃO CONHECIDA (aviso do compilador): PrivilegesRequired=admin move a
; instalação para o hive do administrador; numa instalação interativa manual
; (UAC elevando a própria sessão do usuário) HKCU ainda aponta para o usuário
; correto, mas em deployment silencioso via SCCM/Intune rodando como SYSTEM,
; esta limpeza pode não atingir o hive do usuário final real. Resolver isso de
; verdade exigiria iterar HKEY_USERS por SID, fora do escopo deste script.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "VPNManager"; Flags: deletevalue uninsdeletevalue

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  MarkerPath: string;
  MarkerFile: TArrayOfString;
begin
  if CurStep = ssPostInstall then
  begin
    { Cria o marcador lido por utils.constants._installed_mode_requested():
      sinaliza para o app usar %LOCALAPPDATA%\VPNManager para config/logs em
      vez de tentar escrever ao lado do .exe (Program Files é protegido para
      usuários comuns). Só precisa existir; nunca é reescrito em runtime. }
    MarkerPath := ExpandConstant('{app}\installed.marker');
    SetArrayLength(MarkerFile, 1);
    MarkerFile[0] := 'Criado pelo instalador do VPN Manager ' + '{#MyAppVersion}';
    SaveStringsToFile(MarkerPath, MarkerFile, False);
  end;
end;
