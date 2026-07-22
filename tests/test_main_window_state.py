"""Testes de estado da MainWindow com fakes, cobrindo os cenários do item 32:

- conectar falha e libera _connect_ops_in_flight;
- disconnect falho limpa _user_disconnecting;
- auto-reconnect com backoff tenta de novo e desiste após o limite;
- erro de credencial não aciona backoff (abre diálogo em vez disso);
- cancelamento libera estado sem reabrir diálogo de credenciais.

Usa uma MainWindow real (para exercitar o código de produção), mas com
ConnectionService trocado por um fake que nunca toca rasdial/rede de verdade.
"""
from __future__ import annotations

import time

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

import ui.main_window as mw_module
from core.models import VpnEntry, VpnStatus
from services.connection_service import CANCELLED_MESSAGE
from ui.main_window import MainWindow

KEY = "user:testvpn"

# QApplication de sessão vem de tests/conftest.py (qt_application, autouse).


class FakeConnectionService(QObject):
    operation_finished = Signal(str, str, str, bool, str, float)

    def __init__(self) -> None:
        super().__init__()
        self.connect_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[str] = []
        self._next_result: tuple[bool, str] | None = None
        self.emit_on_connect = True

    def set_next_result(self, success: bool, message: str) -> None:
        self._next_result = (success, message)

    def connect(self, key, name, username=None, password=None, phonebook_path=None):
        self.connect_calls.append((key, name))
        if not self.emit_on_connect:
            return
        success, message = self._next_result
        self.operation_finished.emit(key, name, "connect", success, message, 5.0)

    def reconnect(self, key, name, username=None, password=None, phonebook_path=None):
        self.connect(key, name, username, password, phonebook_path)

    def disconnect(self, key, name):
        pass

    def cancel(self, key):
        self.cancel_calls.append(key)
        self.operation_finished.emit(key, "x", "connect", False, CANCELLED_MESSAGE, 1.0)


@pytest.fixture
def window(monkeypatch: pytest.MonkeyPatch):
    # Backoff acelerado para os testes não demorarem minutos.
    monkeypatch.setattr(mw_module, "_AUTO_RECONNECT_BACKOFF_SECONDS", (0.05, 0.05, 0.05))
    monkeypatch.setattr(mw_module, "_AUTO_RECONNECT_MAX_ATTEMPTS", 3)

    win = MainWindow()
    win._settings_manager.settings.auto_reconnect = True

    fake_service = FakeConnectionService()
    win._connection_service.operation_finished.disconnect(win._on_operation_finished)
    win._connection_service = fake_service
    fake_service.operation_finished.connect(win._on_operation_finished)

    win._notifications: list[tuple[str, str]] = []
    win._notification_service.notify = lambda title, msg, icon=None: win._notifications.append((title, msg))

    yield win, fake_service
    win._shutdown_monitor()


def _pump(condition, timeout_s: float = 3.0) -> None:
    """Processa o loop de eventos Qt até `condition()` ser verdadeira ou o tempo esgotar."""
    app = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()


def test_connect_failure_releases_in_flight_guard(window) -> None:
    win, fake_service = window
    entry = VpnEntry(name="TestVPN", scope="user", status=VpnStatus.DISCONNECTED)
    win._entries = {KEY: entry}
    fake_service.set_next_result(False, "Falha ao conectar (erro 809): rede bloqueada.")

    win._on_connect_requested(KEY)

    assert KEY not in win._connect_ops_in_flight, "guard deveria ser liberado mesmo com falha"


def test_disconnect_failure_clears_user_disconnecting(window) -> None:
    win, fake_service = window
    entry = VpnEntry(name="TestVPN", scope="user", status=VpnStatus.CONNECTED)
    win._entries = {KEY: entry}

    win._on_disconnect_requested(KEY)
    assert KEY in win._user_disconnecting

    win._on_operation_finished(KEY, "TestVPN", "disconnect", False, "Falha ao desconectar: erro X", 5.0)
    assert KEY not in win._user_disconnecting, "não deveria ficar preso para sempre após disconnect falho"


def test_auto_reconnect_backoff_retries_then_gives_up(window) -> None:
    win, fake_service = window
    entry_dropped = VpnEntry(name="TestVPN", scope="user", status=VpnStatus.DISCONNECTED)
    fake_service.set_next_result(False, "Falha ao conectar (erro 809): rede bloqueada.")

    win._start_auto_reconnect(entry_dropped)
    win._entries = {KEY: entry_dropped}  # espelha o que _on_vpns_updated faria de verdade

    _pump(lambda: KEY not in win._auto_reconnect_attempts)

    assert len(fake_service.connect_calls) == 3, fake_service.connect_calls  # 1 inicial + 2 retries
    assert KEY not in win._auto_reconnect_timers
    gave_up = [n for n in win._notifications if "Não foi possível reconectar" in n[1]]
    assert gave_up, win._notifications


def test_credential_error_bypasses_backoff(window) -> None:
    win, fake_service = window
    entry_dropped = VpnEntry(name="TestVPN", scope="user", status=VpnStatus.DISCONNECTED)
    fake_service.set_next_result(False, "Erro 691 de Acesso Remoto - usuário ou senha inválidos.")

    prompts = []
    win._prompt_and_retry_with_credentials = lambda k, n: prompts.append((k, n))

    win._start_auto_reconnect(entry_dropped)

    assert prompts == [(KEY, "TestVPN")]
    assert KEY not in win._auto_reconnect_timers, "erro de credencial não deveria agendar backoff"


def test_cancel_releases_state_without_prompting_credentials(window) -> None:
    win, fake_service = window
    entry = VpnEntry(name="TestVPN", scope="user", status=VpnStatus.DISCONNECTED)
    win._entries = {KEY: entry}
    fake_service.emit_on_connect = False

    prompts = []
    win._prompt_and_retry_with_credentials = lambda k, n: prompts.append((k, n))

    win._on_connect_requested(KEY)
    assert KEY in win._connect_ops_in_flight

    win._on_cancel_requested(KEY)

    assert fake_service.cancel_calls == [KEY]
    assert KEY not in win._connect_ops_in_flight
    assert not prompts


def test_manual_connect_cancels_pending_auto_reconnect_timer(window) -> None:
    win, fake_service = window
    entry_dropped = VpnEntry(name="TestVPN", scope="user", status=VpnStatus.DISCONNECTED)
    fake_service.set_next_result(False, "Falha ao conectar (erro 809): rede bloqueada.")

    win._start_auto_reconnect(entry_dropped)
    win._entries = {KEY: entry_dropped}
    assert KEY in win._auto_reconnect_timers

    fake_service.emit_on_connect = False  # próxima chamada connect() fica "em andamento"
    win._on_connect_requested(KEY)

    assert KEY not in win._auto_reconnect_timers, "clique manual deveria cancelar o backoff pendente"
    assert KEY not in win._auto_reconnect_attempts
