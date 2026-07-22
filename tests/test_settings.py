"""Testes de core.settings: persistência e validação de preferências."""
from __future__ import annotations

import json
from pathlib import Path

from core.settings import AppSettings, SettingsManager


def test_defaults_when_file_does_not_exist(tmp_path: Path) -> None:
    manager = SettingsManager(settings_path=tmp_path / "settings.json")
    assert manager.settings == AppSettings()


def test_invalid_json_falls_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{ isto nao e json valido ", encoding="utf-8")
    manager = SettingsManager(settings_path=path)
    assert manager.settings == AppSettings()


def test_unknown_fields_in_file_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"theme": "dark", "campo_que_nao_existe_mais": 123}), encoding="utf-8")
    manager = SettingsManager(settings_path=path)
    assert manager.settings.theme == "dark"
    assert not hasattr(manager.settings, "campo_que_nao_existe_mais")


def test_clamp_enforces_bounds() -> None:
    settings = AppSettings(refresh_interval=999, command_timeout=1)
    settings.clamp()
    assert settings.refresh_interval == 10  # MAX_REFRESH_INTERVAL
    assert settings.command_timeout == 5  # limite mínimo


def test_update_persists_and_reloads(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    manager = SettingsManager(settings_path=path)
    manager.update(theme="dark", favorite_vpn="MinhaVPN", refresh_interval=7)

    assert path.exists()
    reloaded = SettingsManager(settings_path=path)
    assert reloaded.settings.theme == "dark"
    assert reloaded.settings.favorite_vpn == "MinhaVPN"
    assert reloaded.settings.refresh_interval == 7


def test_update_ignores_unknown_kwargs(tmp_path: Path) -> None:
    manager = SettingsManager(settings_path=tmp_path / "settings.json")
    manager.update(campo_inexistente="valor")  # não deve levantar exceção
    assert not hasattr(manager.settings, "campo_inexistente")
