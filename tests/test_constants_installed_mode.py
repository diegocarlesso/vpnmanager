"""Testes de utils.constants: modo instalado (%LOCALAPPDATA%) e migração automática.

Recarrega o módulo simulando sys.frozen + um diretório de .exe isolado em
tmp_path, para nunca tocar no config/logs reais do projeto.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

# Capturados na coleta do módulo, antes de qualquer monkeypatch: usados para
# restaurar utils.constants ao estado real ao fim de cada teste, sem depender
# da ordem de finalização entre esta fixture e a do monkeypatch (que também
# reverte sys.frozen/executable/env vars, mas não re-executa o módulo sozinho).
_REAL_EXECUTABLE = sys.executable
_REAL_FROZEN = getattr(sys, "frozen", None)
_REAL_LOCALAPPDATA = os.environ.get("LOCALAPPDATA")


def _reload_constants(monkeypatch: pytest.MonkeyPatch, frozen: bool, exe_dir: Path, localappdata: Path):
    """Reimporta utils.constants do zero, com sys.frozen/executable e
    LOCALAPPDATA controlados. A variável VPNMANAGER_APPDATA_MODE (se o teste
    quiser testá-la) deve ser definida pelo próprio teste ANTES de chamar isto —
    esta função não mexe nela, só garante um estado limpo de sys.modules.
    """
    for mod in list(sys.modules):
        if mod.startswith("utils.constants"):
            del sys.modules[mod]
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "VPNManager.exe"), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(localappdata))
    import utils.constants as constants

    importlib.reload(constants)
    return constants


@pytest.fixture
def isolated_dirs(tmp_path: Path):
    tmp_path = tmp_path.resolve()
    exe_dir = tmp_path / "exe"
    localappdata = tmp_path / "localappdata"
    exe_dir.mkdir()
    localappdata.mkdir()
    return exe_dir, localappdata


@pytest.fixture(autouse=True)
def _restore_real_constants_module():
    """Garante que utils.constants volte a refletir o ambiente real ao fim de
    cada teste, independentemente da ordem de finalização com o monkeypatch.

    importlib.reload() deixa o módulo mutado (apontando para diretórios
    temporários); apenas reverter sys.frozen/env vars não re-executa o módulo
    sozinho. Sem isto, outros arquivos de teste (ex.: test_main_window_state.py,
    que constrói uma MainWindow real usando os caminhos padrão) rodando na
    mesma sessão do pytest herdariam esse estado incorreto.
    """
    yield
    if _REAL_FROZEN is None:
        if hasattr(sys, "frozen"):
            delattr(sys, "frozen")
    else:
        sys.frozen = _REAL_FROZEN
    sys.executable = _REAL_EXECUTABLE
    if _REAL_LOCALAPPDATA is None:
        os.environ.pop("LOCALAPPDATA", None)
    else:
        os.environ["LOCALAPPDATA"] = _REAL_LOCALAPPDATA
    os.environ.pop("VPNMANAGER_APPDATA_MODE", None)

    for mod in list(sys.modules):
        if mod.startswith("utils.constants"):
            del sys.modules[mod]
    import utils.constants  # noqa: F401 - reimporta com o ambiente real já restaurado


def test_dev_mode_ignores_installed_signals(monkeypatch: pytest.MonkeyPatch, isolated_dirs) -> None:
    exe_dir, localappdata = isolated_dirs
    (exe_dir / "installed.marker").write_text("")
    monkeypatch.setenv("VPNMANAGER_APPDATA_MODE", "installed")
    c = _reload_constants(monkeypatch, frozen=False, exe_dir=exe_dir, localappdata=localappdata)
    assert c.INSTALLED_MODE is False


def test_frozen_without_any_signal_stays_portable(monkeypatch: pytest.MonkeyPatch, isolated_dirs) -> None:
    exe_dir, localappdata = isolated_dirs
    monkeypatch.delenv("VPNMANAGER_APPDATA_MODE", raising=False)
    c = _reload_constants(monkeypatch, frozen=True, exe_dir=exe_dir, localappdata=localappdata)
    assert c.INSTALLED_MODE is False
    assert c.CONFIG_DIR == exe_dir / "config"
    assert c.LOGS_DIR == exe_dir / "logs"


def test_frozen_with_env_var_uses_localappdata(monkeypatch: pytest.MonkeyPatch, isolated_dirs) -> None:
    exe_dir, localappdata = isolated_dirs
    monkeypatch.setenv("VPNMANAGER_APPDATA_MODE", "installed")
    c = _reload_constants(monkeypatch, frozen=True, exe_dir=exe_dir, localappdata=localappdata)
    assert c.INSTALLED_MODE is True
    assert c.CONFIG_DIR == localappdata / "VPNManager" / "config"
    assert c.LOGS_DIR == localappdata / "VPNManager" / "logs"


def test_frozen_with_marker_file_uses_localappdata(monkeypatch: pytest.MonkeyPatch, isolated_dirs) -> None:
    exe_dir, localappdata = isolated_dirs
    monkeypatch.delenv("VPNMANAGER_APPDATA_MODE", raising=False)
    (exe_dir / "installed.marker").write_text("")
    c = _reload_constants(monkeypatch, frozen=True, exe_dir=exe_dir, localappdata=localappdata)
    assert c.INSTALLED_MODE is True
    assert c.CONFIG_DIR == localappdata / "VPNManager" / "config"


def test_migration_copies_portable_settings_once(monkeypatch: pytest.MonkeyPatch, isolated_dirs) -> None:
    exe_dir, localappdata = isolated_dirs
    old_config = exe_dir / "config"
    old_config.mkdir()
    (old_config / "settings.json").write_text('{"favorite_vpn": "MinhaVPN"}', encoding="utf-8")

    monkeypatch.setenv("VPNMANAGER_APPDATA_MODE", "installed")
    c = _reload_constants(monkeypatch, frozen=True, exe_dir=exe_dir, localappdata=localappdata)

    assert not c.SETTINGS_FILE.exists()
    c.migrate_portable_settings_if_needed()
    assert c.SETTINGS_FILE.exists()
    assert "MinhaVPN" in c.SETTINGS_FILE.read_text(encoding="utf-8")


def test_migration_never_overwrites_existing_destination(monkeypatch: pytest.MonkeyPatch, isolated_dirs) -> None:
    exe_dir, localappdata = isolated_dirs
    old_config = exe_dir / "config"
    old_config.mkdir()
    (old_config / "settings.json").write_text('{"favorite_vpn": "Antiga"}', encoding="utf-8")

    monkeypatch.setenv("VPNMANAGER_APPDATA_MODE", "installed")
    c = _reload_constants(monkeypatch, frozen=True, exe_dir=exe_dir, localappdata=localappdata)
    c.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    c.SETTINGS_FILE.write_text('{"favorite_vpn": "JaConfigurada"}', encoding="utf-8")

    c.migrate_portable_settings_if_needed()
    assert "JaConfigurada" in c.SETTINGS_FILE.read_text(encoding="utf-8")


def test_migration_is_noop_in_portable_mode(monkeypatch: pytest.MonkeyPatch, isolated_dirs) -> None:
    exe_dir, localappdata = isolated_dirs
    monkeypatch.delenv("VPNMANAGER_APPDATA_MODE", raising=False)
    c = _reload_constants(monkeypatch, frozen=True, exe_dir=exe_dir, localappdata=localappdata)
    c.migrate_portable_settings_if_needed()  # não deve levantar exceção nem criar nada
    assert not (localappdata / "VPNManager").exists()
