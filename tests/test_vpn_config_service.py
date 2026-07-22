"""Testes de services.vpn_config_service: workers sempre emitem seus sinais de conclusão."""
from __future__ import annotations

from core.powershell_runner import PsResult
from services.vpn_config_service import _ConfigTask, _DetailsTask

# QApplication de sessão vem de tests/conftest.py (qt_application, autouse).


class _ExplodingManager:
    def add(self, name, **kwargs):
        raise RuntimeError("falha inesperada simulada")

    def update(self, name, **kwargs):
        raise RuntimeError("falha inesperada simulada")

    def delete(self, name, **kwargs):
        raise RuntimeError("falha inesperada simulada")

    def get_details(self, name, all_users):
        raise RuntimeError("falha inesperada simulada em PowerShell")


def test_config_task_emits_finished_on_exception_and_carries_all_users() -> None:
    task = _ConfigTask(_ExplodingManager(), "update", "MyVPN", {"all_users": True})
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))
    task.run()

    assert len(calls) == 1
    name, operation, success, message, partial, all_users = calls[0]
    assert success is False
    assert all_users is True  # reconstrói a chave escopo+nome do lado da UI


def test_config_task_all_users_false_when_missing_from_kwargs() -> None:
    task = _ConfigTask(_ExplodingManager(), "add", "MyVPN", {})
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))
    task.run()
    assert calls[0][5] is False


def test_details_task_emits_none_on_exception_instead_of_hanging() -> None:
    task = _DetailsTask(_ExplodingManager(), "MyVPN", True)
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))
    task.run()

    assert len(calls) == 1
    name, all_users, details = calls[0]
    assert name == "MyVPN"
    assert all_users is True
    assert details is None


class _NormalManager:
    def get_details(self, name, all_users):
        return None  # falha "normal" (não excepcional) já suportada antes desta sessão


def test_details_task_normal_failure_still_emits_none() -> None:
    task = _DetailsTask(_NormalManager(), "MyVPN", False)
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))
    task.run()
    assert calls[0] == ("MyVPN", False, None)


def test_config_task_success_path() -> None:
    class _SucceedingManager:
        def add(self, name, **kwargs):
            return PsResult(True, {}, "")

    task = _ConfigTask(_SucceedingManager(), "add", "MyVPN", {"all_users": False})
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))
    task.run()
    name, operation, success, message, partial, all_users = calls[0]
    assert success is True
    assert "sucesso" in message.lower()
