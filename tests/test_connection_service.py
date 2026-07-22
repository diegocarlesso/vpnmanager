"""Testes de services.connection_service: workers sempre emitem 'finished'."""
from __future__ import annotations

import threading

from core.rasdial_manager import CANCELLED_RETURN_CODE, CommandResult
from services.connection_service import CANCELLED_MESSAGE, _ConnectionTask, _friendly_message

# QApplication de sessão vem de tests/conftest.py (qt_application, autouse).


class _ExplodingRasdialManager:
    def connect(self, name, username=None, password=None, phonebook_path=None, cancel_event=None):
        raise RuntimeError("falha inesperada simulada (bug em subprocess)")

    def disconnect(self, name):
        return CommandResult(True, 0, "", "", 1.0)


class _NormalRasdialManager:
    def __init__(self, result: CommandResult):
        self._result = result

    def connect(self, name, username=None, password=None, phonebook_path=None, cancel_event=None):
        return self._result

    def disconnect(self, name):
        return self._result


def test_connect_task_emits_finished_even_on_unexpected_exception() -> None:
    task = _ConnectionTask(_ExplodingRasdialManager(), "user:x", "MyVPN", "connect", "user", "pass")
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))
    task.run()  # mesma chamada que o QThreadPool faz numa worker thread real

    assert len(calls) == 1
    key, name, operation, success, message, duration_ms = calls[0]
    assert key == "user:x"
    assert name == "MyVPN"
    assert success is False
    assert "Erro inesperado" in message


def test_reconnect_task_also_survives_exception() -> None:
    task = _ConnectionTask(_ExplodingRasdialManager(), "user:x", "MyVPN", "reconnect", "user", "pass")
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))
    task.run()
    assert len(calls) == 1
    assert calls[0][3] is False  # success


def test_friendly_message_maps_cancelled_return_code() -> None:
    result = CommandResult(False, CANCELLED_RETURN_CODE, "", "Cancelado pelo usuário", 5.0)
    assert _friendly_message("connect", result) == CANCELLED_MESSAGE


def test_friendly_message_maps_known_ras_code() -> None:
    result = CommandResult(False, 691, "", "Erro 691 de Acesso Remoto - credenciais inválidas.", 5.0)
    message = _friendly_message("connect", result)
    assert "691" in message
    assert "senha" in message.lower() or "usuário" in message.lower()


def test_friendly_message_falls_back_to_raw_text_for_unknown_code() -> None:
    result = CommandResult(False, -1, "", "Tempo limite excedido", 5.0)
    assert _friendly_message("connect", result) == "Falha ao conectar: Tempo limite excedido"


def test_connect_task_respects_cancel_event() -> None:
    """Task real com um RasdialManager real (processo lento controlável), não um
    mock: confirma que o cancel_event chega até RasdialManager.connect()."""
    import sys
    import time

    from core.rasdial_manager import RasdialManager

    class SlowRasdial(RasdialManager):
        def __init__(self):
            super().__init__(timeout=25, executable=sys.executable)

        def connect(self, name, username=None, password=None, phonebook_path=None, cancel_event=None):
            return self._run(["-c", "import time; time.sleep(30)"], cancel_event=cancel_event)

    cancel_event = threading.Event()
    task = _ConnectionTask(SlowRasdial(), "user:x", "MyVPN", "connect", cancel_event=cancel_event)
    calls = []
    task.signals.finished.connect(lambda *args: calls.append(args))

    def cancel_soon():
        time.sleep(0.5)
        cancel_event.set()

    threading.Thread(target=cancel_soon, daemon=True).start()
    start = time.perf_counter()
    task.run()
    elapsed = time.perf_counter() - start

    assert elapsed < 5
    assert calls[0][4] == CANCELLED_MESSAGE
