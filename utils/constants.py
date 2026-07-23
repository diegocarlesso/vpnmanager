"""Constantes globais compartilhadas pela aplicação."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "VPN Manager"
ORG_NAME = "VPNManager"
APP_VERSION = "1.3.0"

if getattr(sys, "frozen", False):
    # Executando a partir do .exe gerado pelo PyInstaller: por padrão config/logs
    # ficam ao lado do executável (app portátil), enquanto os recursos empacotados
    # (assets) ficam na pasta de extração indicada por sys._MEIPASS.
    BASE_DIR = Path(sys.executable).resolve().parent
    _RESOURCES_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    _RESOURCES_DIR = BASE_DIR

# Diretórios "portáteis" (ao lado do executável): sempre calculados, mesmo em
# modo instalado, para servir de origem de uma migração automática única.
_PORTABLE_CONFIG_DIR = BASE_DIR / "config"
_PORTABLE_LOGS_DIR = BASE_DIR / "logs"
_PORTABLE_SETTINGS_FILE = _PORTABLE_CONFIG_DIR / "settings.json"


def _installed_mode_requested() -> bool:
    """Modo "instalado" (config/logs em %LOCALAPPDATA%) é opt-in — nunca o
    padrão — para não alterar o comportamento de nenhuma instalação portátil já
    existente ao atualizar o executável. Dois sinais são aceitos:

    1. Variável de ambiente VPNMANAGER_APPDATA_MODE=installed (útil para testes
       manuais ou scripts de deployment como Intune/SCCM);
    2. Um arquivo "installed.marker" ao lado do executável, criado pelo próprio
       instalador (installer/vpnmanager.iss) durante a instalação em um diretório
       protegido como Program Files, onde o usuário comum não pode escrever ao
       lado do .exe (por isso o marcador só precisa existir, nunca ser reescrito
       em tempo de execução).
    """
    if os.environ.get("VPNMANAGER_APPDATA_MODE", "").strip().casefold() == "installed":
        return True
    return (BASE_DIR / "installed.marker").exists()


INSTALLED_MODE = getattr(sys, "frozen", False) and _installed_mode_requested()

if INSTALLED_MODE:
    _local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    _USER_DATA_DIR = _local_appdata / ORG_NAME
    CONFIG_DIR = _USER_DATA_DIR / "config"
    LOGS_DIR = _USER_DATA_DIR / "logs"
else:
    CONFIG_DIR = _PORTABLE_CONFIG_DIR
    LOGS_DIR = _PORTABLE_LOGS_DIR

ASSETS_DIR = _RESOURCES_DIR / "assets"
SCRIPTS_DIR = _RESOURCES_DIR / "scripts"
SETTINGS_FILE = CONFIG_DIR / "settings.json"

POWERSHELL_EXE = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
DEFAULT_PS_TIMEOUT = 20
ELEVATED_PS_TIMEOUT = 150

_APPDATA = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
_PROGRAMDATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))

USER_PBK_PATH = _APPDATA / "Microsoft" / "Network" / "Connections" / "Pbk" / "rasphone.pbk"
SYSTEM_PBK_PATH = _PROGRAMDATA / "Microsoft" / "Network" / "Connections" / "Pbk" / "rasphone.pbk"

DEFAULT_REFRESH_INTERVAL = 5
MIN_REFRESH_INTERVAL = 2
MAX_REFRESH_INTERVAL = 10
DEFAULT_COMMAND_TIMEOUT = 15

REGISTRY_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REGISTRY_RUN_VALUE_NAME = "VPNManager"


def migrate_portable_settings_if_needed() -> None:
    """Copia settings.json do local portátil (ao lado do .exe) para
    %LOCALAPPDATA% na primeira execução em modo instalado.

    Sem isto, qualquer instalação que já rodava em modo portátil perderia
    silenciosamente suas preferências (VPN favorita, diretório PBK customizado,
    intervalo etc.) ao passar a rodar em modo instalado, pois o app passaria a
    ler um settings.json que nunca existiu no novo local. Idempotente: não faz
    nada se o modo instalado não estiver ativo, se não houver nada para migrar,
    ou se o destino já tiver um settings.json (nunca sobrescreve).
    """
    if not INSTALLED_MODE:
        return
    if SETTINGS_FILE.exists():
        return
    if not _PORTABLE_SETTINGS_FILE.exists():
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_bytes(_PORTABLE_SETTINGS_FILE.read_bytes())
    except OSError:
        # Falha na migração não deve impedir o app de iniciar: na pior das
        # hipóteses, o usuário reconfigura as preferências manualmente.
        pass
