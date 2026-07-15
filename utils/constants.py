"""Constantes globais compartilhadas pela aplicação."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "VPN Manager"
ORG_NAME = "VPNManager"
APP_VERSION = "1.0.0"

if getattr(sys, "frozen", False):
    # Executando a partir do .exe gerado pelo PyInstaller: config/logs ficam
    # ao lado do executável (app portátil), enquanto os recursos empacotados
    # (assets) ficam na pasta de extração indicada por sys._MEIPASS.
    BASE_DIR = Path(sys.executable).resolve().parent
    _RESOURCES_DIR = Path(getattr(sys, "_MEIPASS", BASE_DIR))
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    _RESOURCES_DIR = BASE_DIR

CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs"
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
