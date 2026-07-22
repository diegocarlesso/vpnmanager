"""Testes de core.credential_store.

Usa o Windows Credential Manager real (DPAPI) — não há como simular fielmente
CredReadW/CredWriteW sem reimplementar a API. Para não arriscar tocar em
credenciais de VPNs reais do usuário, todo teste usa um nome de VPN exclusivo
de teste e limpa o Credential Manager antes/depois via fixture.
"""
from __future__ import annotations

import pytest

from core import credential_store

_TEST_VPN = "___pytest_vpn_manager_credential_store_test___"


@pytest.fixture(autouse=True)
def _clean_test_credential():
    credential_store.delete_credentials(_TEST_VPN)
    yield
    credential_store.delete_credentials(_TEST_VPN)


def test_has_saved_credentials_false_when_nothing_saved() -> None:
    assert credential_store.has_saved_credentials(_TEST_VPN) is False


def test_load_credentials_returns_none_when_nothing_saved() -> None:
    username, password = credential_store.load_credentials(_TEST_VPN)
    assert username is None
    assert password is None


def test_save_then_load_roundtrip() -> None:
    assert credential_store.save_credentials(_TEST_VPN, "usuario1", "senha-com-acentuação-áéí") is True
    username, password = credential_store.load_credentials(_TEST_VPN)
    assert username == "usuario1"
    assert password == "senha-com-acentuação-áéí"


def test_has_saved_credentials_true_after_save() -> None:
    credential_store.save_credentials(_TEST_VPN, "usuario1", "senha1")
    assert credential_store.has_saved_credentials(_TEST_VPN) is True


def test_save_overwrites_previous_value() -> None:
    credential_store.save_credentials(_TEST_VPN, "usuario1", "senha1")
    credential_store.save_credentials(_TEST_VPN, "usuario2", "senha2")
    username, password = credential_store.load_credentials(_TEST_VPN)
    assert username == "usuario2"
    assert password == "senha2"


def test_delete_removes_credential() -> None:
    credential_store.save_credentials(_TEST_VPN, "usuario1", "senha1")
    assert credential_store.delete_credentials(_TEST_VPN) is True
    assert credential_store.has_saved_credentials(_TEST_VPN) is False


def test_delete_when_nothing_saved_does_not_raise() -> None:
    # Não deve levantar exceção mesmo sem nada para excluir.
    credential_store.delete_credentials(_TEST_VPN)


def test_target_name_is_case_insensitive() -> None:
    credential_store.save_credentials(_TEST_VPN.upper(), "usuario1", "senha1")
    assert credential_store.has_saved_credentials(_TEST_VPN.lower()) is True
