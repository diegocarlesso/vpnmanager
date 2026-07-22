"""Testes de core.pbk_parser: leitura/interpretação de arquivos .pbk."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.pbk_parser import PbkParser


def _write(path: Path, content: str, encoding: str = "utf-8") -> None:
    path.write_bytes(content.encode(encoding))


def test_parses_basic_vpn_entry(tmp_path: Path) -> None:
    pbk = tmp_path / "rasphone.pbk"
    _write(pbk, "[MinhaVPN]\nMedia=Rastapi\nPhoneNumber=10.0.0.1\nDevice=WAN Miniport (IKEv2)\n")

    parser = PbkParser(custom_directory=str(tmp_path))
    entries = parser.get_all_vpn_entries()

    assert len(entries) == 1
    entry = next(iter(entries.values()))
    assert entry.name == "MinhaVPN"
    assert entry.server == "10.0.0.1"
    assert entry.conn_type == "VPN"
    assert entry.phonebook_path == str(pbk)


def test_utf8_bom_encoding_is_readable(tmp_path: Path) -> None:
    pbk = tmp_path / "rasphone.pbk"  # get_pbk_paths() só procura por esse nome exato
    _write(pbk, "[VPN Ação]\nMedia=Rastapi\nPhoneNumber=1.1.1.1\n", encoding="utf-8-sig")
    parser = PbkParser(custom_directory=str(tmp_path))
    entries = parser.get_all_vpn_entries()
    assert any(e.name == "VPN Ação" for e in entries.values())


def test_cp1252_encoding_is_readable(tmp_path: Path) -> None:
    pbk = tmp_path / "rasphone.pbk"
    _write(pbk, "[VPN Ação]\nMedia=Rastapi\nPhoneNumber=1.1.1.1\n", encoding="cp1252")
    parser = PbkParser(custom_directory=str(tmp_path))
    entries = parser.get_all_vpn_entries()
    assert any(e.name == "VPN Ação" for e in entries.values())


def test_invalid_file_returns_no_entries_without_raising(tmp_path: Path) -> None:
    pbk = tmp_path / "rasphone.pbk"
    pbk.write_bytes(b"\xff\xfe\x00\x01isto n\xe3o \xe9 um pbk v\xe1lido {{{[[[")
    parser = PbkParser(custom_directory=str(tmp_path))
    # Não deve levantar exceção mesmo com conteúdo corrompido/binário.
    entries = parser.get_all_vpn_entries()
    assert isinstance(entries, dict)


def test_missing_pbk_file_returns_empty(tmp_path: Path) -> None:
    parser = PbkParser(custom_directory=str(tmp_path))  # diretório existe, mas sem rasphone.pbk
    assert parser.get_all_vpn_entries() == {}


def test_custom_directory_forces_user_scope(tmp_path: Path) -> None:
    pbk = tmp_path / "rasphone.pbk"
    _write(pbk, "[VPN1]\nMedia=Rastapi\nPhoneNumber=1.2.3.4\n")
    parser = PbkParser(custom_directory=str(tmp_path))
    entries = parser.get_all_vpn_entries()
    entry = next(iter(entries.values()))
    assert entry.scope == "user"
    assert entry.key() == "user:vpn1"


def test_duplicate_name_across_scopes_creates_two_distinct_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user_pbk = tmp_path / "user_rasphone.pbk"
    system_pbk = tmp_path / "system_rasphone.pbk"
    _write(user_pbk, "[Compartilhada]\nMedia=Rastapi\nPhoneNumber=1.1.1.1\n")
    _write(system_pbk, "[Compartilhada]\nMedia=Rastapi\nPhoneNumber=2.2.2.2\n")

    import core.pbk_parser as pbk_module

    monkeypatch.setattr(pbk_module, "USER_PBK_PATH", user_pbk)
    monkeypatch.setattr(pbk_module, "SYSTEM_PBK_PATH", system_pbk)

    parser = PbkParser()  # sem diretório customizado: lê os dois phonebooks "padrão"
    entries = parser.get_all_vpn_entries()

    assert len(entries) == 2
    assert "user:compartilhada" in entries
    assert "system:compartilhada" in entries
    assert entries["user:compartilhada"].server == "1.1.1.1"
    assert entries["system:compartilhada"].server == "2.2.2.2"
    assert entries["user:compartilhada"].duplicate_name is True
    assert entries["system:compartilhada"].duplicate_name is True


def test_unique_name_is_not_flagged_as_duplicate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    user_pbk = tmp_path / "user_rasphone.pbk"
    system_pbk = tmp_path / "system_rasphone.pbk"
    _write(user_pbk, "[SoUsuario]\nMedia=Rastapi\nPhoneNumber=1.1.1.1\n")
    _write(system_pbk, "[SoSistema]\nMedia=Rastapi\nPhoneNumber=2.2.2.2\n")

    import core.pbk_parser as pbk_module

    monkeypatch.setattr(pbk_module, "USER_PBK_PATH", user_pbk)
    monkeypatch.setattr(pbk_module, "SYSTEM_PBK_PATH", system_pbk)

    parser = PbkParser()
    entries = parser.get_all_vpn_entries()
    assert all(not e.duplicate_name for e in entries.values())
