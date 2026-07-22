"""Testes de core.ras_errors: extração e mapeamento de códigos RAS."""
from __future__ import annotations

from core.ras_errors import CREDENTIAL_ERROR_CODE, describe_ras_error, extract_ras_error_code


def test_extracts_code_from_localized_message() -> None:
    msg = "Erro 691 de Acesso Remoto - Acesso negado devido a nome de usuário ou senha inválidos."
    assert extract_ras_error_code(msg) == "691"


def test_extracts_code_from_english_message() -> None:
    msg = "Error 633: The port is already in use or is not configured for Remote Access dialout."
    assert extract_ras_error_code(msg) == "633"


def test_returns_none_when_no_code_present() -> None:
    assert extract_ras_error_code("Tempo limite excedido") is None
    assert extract_ras_error_code("") is None


def test_describes_known_codes() -> None:
    assert describe_ras_error("Erro 691 de Acesso Remoto - ...") == "Usuário ou senha inválidos."
    assert describe_ras_error("Erro 623 de Acesso Remoto - ...") is not None
    assert describe_ras_error("Erro 868 de Acesso Remoto - ...") is not None


def test_describe_returns_none_for_unknown_code() -> None:
    assert describe_ras_error("Erro 99999 de Acesso Remoto - código nunca visto") is None


def test_credential_error_code_constant_matches_691() -> None:
    assert CREDENTIAL_ERROR_CODE == "691"
