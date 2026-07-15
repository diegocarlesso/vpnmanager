# VPN Manager

Gerenciador profissional de conexões VPN do Windows, baseado nos arquivos
`.pbk` do RAS e no utilitário `rasdial.exe`. Interface desktop construída com
Python 3.13 e PySide6, priorizando desempenho, estabilidade e baixo consumo
de memória.

## Requisitos

* Windows 10/11
* Python 3.13+
* Permissão de usuário para executar `rasdial.exe` (não requer administrador
  para conectar/desconectar VPNs já cadastradas no Windows)

## Instalação

```powershell
cd vpn_manager
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Execução

```powershell
python main.py
```

A aplicação:

* Lê automaticamente `%APPDATA%\Microsoft\Network\Connections\Pbk\rasphone.pbk`
  e `C:\ProgramData\Microsoft\Network\Connections\Pbk\rasphone.pbk`.
* Atualiza o estado das conexões a cada N segundos (configurável entre 2 e 10
  em **Configurações**), detectando inclusive conexões feitas fora do
  programa (via `rasdial`, painel de rede do Windows, etc).
* Minimiza para a bandeja do sistema ao fechar (configurável).
* Grava logs em `logs/vpn-manager-YYYY-MM-DD.log` (rotação por tamanho, até
  7 arquivos de backup).

## Estrutura do projeto

```text
vpn_manager/
├── main.py
├── requirements.txt
├── assets/
├── config/            # settings.json é criado aqui na primeira execução
├── logs/
├── core/
│   ├── pbk_parser.py       # leitura dos arquivos .pbk
│   ├── rasdial_manager.py  # wrapper de subprocess sobre rasdial.exe
│   ├── vpn_monitor.py      # polling periódico em QThread dedicada
│   ├── models.py           # dataclasses (VpnEntry, VpnStatus, ...)
│   └── settings.py         # persistência de preferências
├── ui/
│   ├── main_window.py
│   ├── vpn_widget.py
│   ├── settings_dialog.py
│   └── log_window.py
├── services/
│   ├── connection_service.py    # operações assíncronas (QThreadPool)
│   └── notification_service.py  # notificações na bandeja do sistema
└── utils/
    ├── logger.py
    ├── helpers.py
    └── constants.py
```

## Segurança

* Senhas informadas em tempo real (diálogo de credenciais) são passadas
  diretamente ao `rasdial.exe` via `subprocess` e **nunca** são gravadas em
  disco ou em log.
* Os logs sanitizam mensagens de erro para nunca incluir credenciais.
* Subprocessos rodam com timeout configurável e `CREATE_NO_WINDOW`, sem abrir
  janelas de console.

## Build para Windows (executável único)

```powershell
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name "VPNManager" main.py
```

O executável final ficará em `dist/VPNManager.exe`. Para usar um ícone
personalizado, adicione `--icon assets/app.ico` ao comando acima.

> Observação: como a aplicação lê e escreve arquivos em `config/` e `logs/`
> relativos ao diretório do projeto, ao distribuir o `.exe` isolado
> certifique-se de que o processo tenha permissão de escrita no diretório em
> que ele for executado (ou ajuste `utils/constants.py` para apontar para
> `%LOCALAPPDATA%` em builds empacotados).

## Licença

Uso interno / corporativo.
