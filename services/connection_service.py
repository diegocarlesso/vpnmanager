"""Serviço de alto nível para operações de conexão VPN, executadas em segundo plano."""
from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from core.ras_errors import describe_ras_error, extract_ras_error_code
from core.rasdial_manager import CANCELLED_RETURN_CODE, CommandResult, RasdialManager
from utils.helpers import sanitize_for_log

logger = logging.getLogger("vpn_manager.connection")

# Mensagem exata usada quando o usuário cancela uma conexão em andamento (botão
# "Cancelar"): a UI compara com esse valor para não tratar o cancelamento como
# uma falha real (não deve reabrir o diálogo de credenciais nem acionar backoff
# de reconexão automática).
CANCELLED_MESSAGE = "Conexão cancelada pelo usuário."


class _ConnectionSignals(QObject):
    finished = Signal(str, str, str, bool, str, float)  # key, name, operation, success, message, duration_ms


class _ConnectionTask(QRunnable):
    """Executa uma única operação (connect/disconnect/reconnect) em uma worker thread."""

    def __init__(
        self,
        rasdial_manager: RasdialManager,
        key: str,
        name: str,
        operation: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        phonebook_path: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._rasdial_manager = rasdial_manager
        self._key = key
        self._name = name
        self._operation = operation
        self._username = username
        self._password = password
        self._phonebook_path = phonebook_path
        self._cancel_event = cancel_event
        self.signals = _ConnectionSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self._operation == "connect":
                result = self._rasdial_manager.connect(
                    self._name, self._username, self._password, self._phonebook_path, self._cancel_event
                )
            elif self._operation == "disconnect":
                result = self._rasdial_manager.disconnect(self._name)
            elif self._operation == "reconnect":
                self._rasdial_manager.disconnect(self._name)
                result = self._rasdial_manager.connect(
                    self._name, self._username, self._password, self._phonebook_path, self._cancel_event
                )
            else:
                result = CommandResult(False, -1, "", f"Operação desconhecida: {self._operation}", 0.0)
        except Exception as exc:  # noqa: BLE001 - sem isso, 'finished' nunca é emitido e a UI trava o botão
            logger.exception("Erro inesperado em '%s' para '%s'", self._operation, self._name)
            self.signals.finished.emit(
                self._key, self._name, self._operation, False, f"Erro inesperado: {exc}", 0.0
            )
            return

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

        self.signals.finished.emit(
            self._key, self._name, self._operation, result.success, message, result.duration_ms
        )


def _friendly_message(operation: str, result: CommandResult) -> str:
    if result.success:
        return {
            "connect": "Conectado com sucesso.",
            "disconnect": "Desconectado com sucesso.",
            "reconnect": "Reconectado com sucesso.",
        }.get(operation, "Operação concluída.")
    if result.return_code == CANCELLED_RETURN_CODE:
        return CANCELLED_MESSAGE
    detail = sanitize_for_log(result.stderr or result.stdout) or "Erro desconhecido."
    verbs = {"connect": "conectar", "disconnect": "desconectar", "reconnect": "reconectar"}
    prefix = f"Falha ao {verbs.get(operation, operation)}"
    code = extract_ras_error_code(detail)
    description = describe_ras_error(detail)
    if description:
        # Descrição estável por código, independente do idioma do Windows;
        # mantém o texto bruto do rasdial em seguida para quem quiser o detalhe original.
        return f"{prefix} (erro {code}): {description}"
    return f"{prefix}: {detail}"


class ConnectionService(QObject):
    """Ponto único para solicitar conexões/desconexões sem bloquear a interface."""

    operation_finished = Signal(str, str, str, bool, str, float)  # key, name, operation, success, message, duration_ms

    def __init__(self, rasdial_manager: RasdialManager) -> None:
        super().__init__()
        self._rasdial_manager = rasdial_manager
        self._pool = QThreadPool.globalInstance()
        # Apenas operações connect/reconnect são canceláveis (são as demoradas);
        # indexado pela mesma chave escopo+nome usada em toda a UI.
        self._active_cancel_events: Dict[str, threading.Event] = {}

    def connect(
        self,
        key: str,
        name: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        phonebook_path: Optional[str] = None,
    ) -> None:
        self._submit(key, name, "connect", username, password, phonebook_path)

    def disconnect(self, key: str, name: str) -> None:
        self._submit(key, name, "disconnect")

    def reconnect(
        self,
        key: str,
        name: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        phonebook_path: Optional[str] = None,
    ) -> None:
        self._submit(key, name, "reconnect", username, password, phonebook_path)

    def cancel(self, key: str) -> None:
        """Pede para interromper a conexão em andamento para `key`, se houver uma.

        Best-effort: se a operação já tiver terminado (ou nunca ter existido),
        não faz nada.
        """
        event = self._active_cancel_events.get(key)
        if event is not None:
            event.set()

    def _submit(
        self,
        key: str,
        name: str,
        operation: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        phonebook_path: Optional[str] = None,
    ) -> None:
        cancel_event = threading.Event() if operation in ("connect", "reconnect") else None
        task = _ConnectionTask(
            self._rasdial_manager, key, name, operation, username, password, phonebook_path, cancel_event
        )
        if cancel_event is not None:
            self._active_cancel_events[key] = cancel_event
        task.signals.finished.connect(self._on_task_finished)
        self._pool.start(task)

    def _on_task_finished(
        self, key: str, name: str, operation: str, success: bool, message: str, duration_ms: float
    ) -> None:
        self._active_cancel_events.pop(key, None)
        self.operation_finished.emit(key, name, operation, success, message, duration_ms)
