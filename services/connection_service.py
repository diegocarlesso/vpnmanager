"""Serviço de alto nível para operações de conexão VPN, executadas em segundo plano."""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from core.rasdial_manager import CommandResult, RasdialManager
from utils.helpers import sanitize_for_log

logger = logging.getLogger("vpn_manager.connection")


class _ConnectionSignals(QObject):
    finished = Signal(str, str, bool, str, float)  # name, operation, success, message, duration_ms


class _ConnectionTask(QRunnable):
    """Executa uma única operação (connect/disconnect/reconnect) em uma worker thread."""

    def __init__(
        self,
        rasdial_manager: RasdialManager,
        name: str,
        operation: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._rasdial_manager = rasdial_manager
        self._name = name
        self._operation = operation
        self._username = username
        self._password = password
        self.signals = _ConnectionSignals()

    @Slot()
    def run(self) -> None:
        if self._operation == "connect":
            result = self._rasdial_manager.connect(self._name, self._username, self._password)
        elif self._operation == "disconnect":
            result = self._rasdial_manager.disconnect(self._name)
        elif self._operation == "reconnect":
            self._rasdial_manager.disconnect(self._name)
            result = self._rasdial_manager.connect(self._name, self._username, self._password)
        else:
            result = CommandResult(False, -1, "", f"Operação desconhecida: {self._operation}", 0.0)

        message = _friendly_message(self._operation, result)

        # Nunca registrar usuário/senha no log; apenas nome da VPN, operação e resultado.
        logger.info(
            "Operação '%s' em '%s' -> sucesso=%s tempo=%.1fms",
            self._operation,
            self._name,
            result.success,
            result.duration_ms,
        )
        if not result.success:
            logger.warning(
                "Falha em '%s' para '%s': %s",
                self._operation,
                self._name,
                sanitize_for_log(result.stderr or result.stdout),
            )

        self.signals.finished.emit(self._name, self._operation, result.success, message, result.duration_ms)


def _friendly_message(operation: str, result: CommandResult) -> str:
    if result.success:
        return {
            "connect": "Conectado com sucesso.",
            "disconnect": "Desconectado com sucesso.",
            "reconnect": "Reconectado com sucesso.",
        }.get(operation, "Operação concluída.")
    detail = sanitize_for_log(result.stderr or result.stdout) or "Erro desconhecido."
    verbs = {"connect": "conectar", "disconnect": "desconectar", "reconnect": "reconectar"}
    return f"Falha ao {verbs.get(operation, operation)}: {detail}"


class ConnectionService(QObject):
    """Ponto único para solicitar conexões/desconexões sem bloquear a interface."""

    operation_finished = Signal(str, str, bool, str, float)

    def __init__(self, rasdial_manager: RasdialManager) -> None:
        super().__init__()
        self._rasdial_manager = rasdial_manager
        self._pool = QThreadPool.globalInstance()

    def connect(self, name: str, username: Optional[str] = None, password: Optional[str] = None) -> None:
        self._submit(name, "connect", username, password)

    def disconnect(self, name: str) -> None:
        self._submit(name, "disconnect")

    def reconnect(self, name: str, username: Optional[str] = None, password: Optional[str] = None) -> None:
        self._submit(name, "reconnect", username, password)

    def _submit(
        self, name: str, operation: str, username: Optional[str] = None, password: Optional[str] = None
    ) -> None:
        task = _ConnectionTask(self._rasdial_manager, name, operation, username, password)
        task.signals.finished.connect(self.operation_finished.emit)
        self._pool.start(task)
