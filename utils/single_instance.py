"""Garante que apenas uma instância da aplicação rode por vez.

Uma segunda instância detecta a primeira através de um QLocalServer nomeado:
se conseguir se conectar a ele, apenas envia um pedido para trazer a janela
existente para frente e encerra (sem abrir uma segunda janela/monitor/ícone
de bandeja duplicados).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger("vpn_manager.singleinstance")

_SERVER_NAME = "VPNManager-SingleInstance-2f6e1a9c"
_CONNECT_TIMEOUT_MS = 250


class SingleInstanceGuard(QObject):
    """Coordena a instância única via um socket local nomeado."""

    show_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._server: QLocalServer | None = None

    def try_acquire(self) -> bool:
        """Retorna True se esta instância deve continuar iniciando (é a primária)."""
        probe = QLocalSocket()
        probe.connectToServer(_SERVER_NAME)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            probe.write(b"show")
            probe.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            probe.disconnectFromServer()
            return False

        # Nenhuma instância respondeu: pode haver um socket "orfão" de um
        # encerramento anormal anterior — remove antes de assumir o papel de
        # instância primária.
        QLocalServer.removeServer(_SERVER_NAME)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(_SERVER_NAME):
            logger.warning(
                "Não foi possível iniciar o servidor de instância única: %s", self._server.errorString()
            )
        return True

    def _on_new_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda: self._on_ready_read(socket))
        socket.disconnected.connect(socket.deleteLater)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        socket.readAll()
        self.show_requested.emit()
