"""Testes de core.rasdial_manager: parsing de saída e execução cancelável."""
from __future__ import annotations

import sys
import threading
import time

import pytest

from core.rasdial_manager import CANCELLED_RETURN_CODE, CommandResult, RasdialManager


def _result(stdout: str) -> CommandResult:
    return CommandResult(success=True, return_code=0, stdout=stdout, stderr="", duration_ms=1.0)


class TestParseActiveConnections:
    def test_no_active_connections(self) -> None:
        # Saída típica quando não há nada conectado: cabeçalho + rodapé, sem nome no meio.
        stdout = "Nome do dispositivo de RAS      Nome do dispositivo de rede\nComando concluído com êxito."
        assert RasdialManager.parse_active_connections(_result(stdout)) == set()

    def test_one_active_connection(self) -> None:
        stdout = "Cabeçalho\nMinhaVPN\nComando concluído com êxito."
        assert RasdialManager.parse_active_connections(_result(stdout)) == {"MinhaVPN"}

    def test_multiple_active_connections(self) -> None:
        stdout = "Cabeçalho\nVPN1\nVPN2\nVPN3\nRodapé"
        assert RasdialManager.parse_active_connections(_result(stdout)) == {"VPN1", "VPN2", "VPN3"}

    def test_localized_english_output(self) -> None:
        stdout = "Connected to\nMyVPN\nCommand completed successfully."
        assert RasdialManager.parse_active_connections(_result(stdout)) == {"MyVPN"}

    def test_unexpected_short_output_returns_empty(self) -> None:
        assert RasdialManager.parse_active_connections(_result("")) == set()
        assert RasdialManager.parse_active_connections(_result("uma linha só")) == set()


class TestConnectArgs:
    def test_no_phonebook_no_credentials(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}
        mgr = RasdialManager(executable="rasdial.exe")
        monkeypatch.setattr(mgr, "_run", lambda args, **kw: captured.setdefault("args", args) or CommandResult(True, 0, "", "", 1.0))
        mgr.connect("MinhaVPN")
        assert captured["args"] == ["MinhaVPN"]

    def test_with_credentials_and_phonebook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = {}
        mgr = RasdialManager(executable="rasdial.exe")
        monkeypatch.setattr(mgr, "_run", lambda args, **kw: captured.setdefault("args", args) or CommandResult(True, 0, "", "", 1.0))
        mgr.connect("MinhaVPN", username="user1", password="pass1", phonebook_path=r"C:\a\rasphone.pbk")
        assert captured["args"] == ["MinhaVPN", "user1", "pass1", r"/PHONEBOOK:C:\a\rasphone.pbk"]

    def test_disconnect_never_gets_phonebook_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # rasdial.exe /? não lista /PHONEBOOK na forma "entryname /DISCONNECT".
        captured = {}
        mgr = RasdialManager(executable="rasdial.exe")
        monkeypatch.setattr(mgr, "_run", lambda args, **kw: captured.setdefault("args", args) or CommandResult(True, 0, "", "", 1.0))
        mgr.disconnect("MinhaVPN")
        assert captured["args"] == ["MinhaVPN", "/disconnect"]


class _SlowProcessManager(RasdialManager):
    """Usa o próprio interpretador Python como processo "lento" controlável,
    em vez do rasdial.exe de verdade, para testar o loop de polling/cancelamento
    sem tocar em nenhuma VPN real."""

    def __init__(self, sleep_seconds: float, timeout: int) -> None:
        super().__init__(timeout=timeout, executable=sys.executable)
        self._sleep_seconds = sleep_seconds

    def args(self):
        return ["-c", f"import time; time.sleep({self._sleep_seconds})"]


class TestCancellableRun:
    def test_cancel_event_interrupts_before_timeout(self) -> None:
        mgr = _SlowProcessManager(sleep_seconds=30, timeout=25)
        cancel_event = threading.Event()

        def cancel_soon():
            time.sleep(0.5)
            cancel_event.set()

        threading.Thread(target=cancel_soon, daemon=True).start()

        start = time.perf_counter()
        result = mgr._run(mgr.args(), cancel_event=cancel_event)
        elapsed = time.perf_counter() - start

        assert result.success is False
        assert result.return_code == CANCELLED_RETURN_CODE
        assert elapsed < 5, f"cancelamento deveria responder rápido, levou {elapsed:.2f}s"

    def test_timeout_without_cancel_event_still_works(self) -> None:
        mgr = _SlowProcessManager(sleep_seconds=10, timeout=1)
        start = time.perf_counter()
        result = mgr._run(mgr.args())
        elapsed = time.perf_counter() - start

        assert result.success is False
        assert result.return_code == -1
        assert result.stderr == "Tempo limite excedido"
        assert elapsed < 3

    def test_process_finishing_normally_still_works(self) -> None:
        mgr = _SlowProcessManager(sleep_seconds=0.2, timeout=10)
        result = mgr._run(mgr.args())
        assert result.success is True
        assert result.return_code == 0
