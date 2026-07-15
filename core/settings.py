"""Gerenciamento de configurações persistentes da aplicação (config/settings.json)."""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from utils.constants import (
    CONFIG_DIR,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_REFRESH_INTERVAL,
    MAX_REFRESH_INTERVAL,
    MIN_REFRESH_INTERVAL,
    REGISTRY_RUN_KEY,
    REGISTRY_RUN_VALUE_NAME,
    SETTINGS_FILE,
)

logger = logging.getLogger("vpn_manager.settings")


@dataclass
class AppSettings:
    """Conjunto de preferências configuráveis pelo usuário."""

    refresh_interval: int = DEFAULT_REFRESH_INTERVAL
    start_with_windows: bool = False
    theme: str = "light"
    favorite_vpn: Optional[str] = None
    command_timeout: int = DEFAULT_COMMAND_TIMEOUT
    pbk_directory: Optional[str] = None
    minimize_to_tray: bool = True
    auto_reconnect: bool = False
    start_minimized: bool = False

    def clamp(self) -> None:
        """Garante que os valores numéricos permaneçam dentro dos limites suportados."""
        self.refresh_interval = max(MIN_REFRESH_INTERVAL, min(MAX_REFRESH_INTERVAL, self.refresh_interval))
        self.command_timeout = max(5, min(120, self.command_timeout))


class SettingsManager:
    """Carrega, persiste e aplica as configurações da aplicação."""

    def __init__(self, settings_path: Path = SETTINGS_FILE) -> None:
        self._settings_path = settings_path
        self._settings = self._load()

    @property
    def settings(self) -> AppSettings:
        return self._settings

    def _load(self) -> AppSettings:
        if not self._settings_path.exists():
            return AppSettings()
        try:
            data = json.loads(self._settings_path.read_text(encoding="utf-8"))
            known_fields = set(AppSettings.__dataclass_fields__)
            filtered = {k: v for k, v in data.items() if k in known_fields}
            settings = AppSettings(**filtered)
            settings.clamp()
            return settings
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("Não foi possível ler settings.json (%s); usando padrões.", exc)
            return AppSettings()

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            self._settings.clamp()
            self._settings_path.write_text(
                json.dumps(asdict(self._settings), indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            logger.error("Falha ao salvar configurações: %s", exc)

    def update(self, **kwargs) -> None:
        """Atualiza os campos informados e persiste imediatamente em disco."""
        for key, value in kwargs.items():
            if hasattr(self._settings, key):
                setattr(self._settings, key, value)
        self.save()

    def apply_startup_registration(self) -> None:
        """Registra ou remove a aplicação da inicialização automática do Windows."""
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_RUN_KEY, 0, winreg.KEY_SET_VALUE)
            try:
                if self._settings.start_with_windows:
                    if getattr(sys, "frozen", False):
                        exe_path = f'"{sys.executable}"'
                    else:
                        main_script = Path(__file__).resolve().parent.parent / "main.py"
                        exe_path = f'"{sys.executable}" "{main_script}"'
                    winreg.SetValueEx(key, REGISTRY_RUN_VALUE_NAME, 0, winreg.REG_SZ, exe_path)
                else:
                    try:
                        winreg.DeleteValue(key, REGISTRY_RUN_VALUE_NAME)
                    except FileNotFoundError:
                        pass
            finally:
                winreg.CloseKey(key)
        except OSError as exc:
            logger.error("Falha ao configurar inicialização automática: %s", exc)
