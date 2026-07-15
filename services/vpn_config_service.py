"""Serviço de alto nível para operações de configuração de VPN (adicionar/editar/excluir/detalhes)."""
from __future__ import annotations

import logging
from typing import List

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from core.powershell_runner import PsResult
from core.vpn_config_manager import VpnConfigManager

logger = logging.getLogger("vpn_manager.vpnconfigservice")


class _ConfigSignals(QObject):
    finished = Signal(str, str, bool, str, bool)  # name, operation, success, message, partial


class _DetailsSignals(QObject):
    finished = Signal(str, bool, object)  # name, all_users, Optional[VpnConnectionDetails]


class _ConfigTask(QRunnable):
    """Executa uma única operação (add/update/delete) em uma worker thread dedicada."""

    def __init__(self, manager: VpnConfigManager, operation: str, name: str, kwargs: dict) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._manager = manager
        self._operation = operation
        self._name = name
        self._kwargs = kwargs
        self.signals = _ConfigSignals()

    @Slot()
    def run(self) -> None:
        try:
            if self._operation == "add":
                result = self._manager.add(self._name, **self._kwargs)
            elif self._operation == "update":
                result = self._manager.update(self._name, **self._kwargs)
            elif self._operation == "delete":
                result = self._manager.delete(self._name, **self._kwargs)
            else:
                result = PsResult(False, {}, f"Operação desconhecida: {self._operation}")
        except Exception as exc:  # noqa: BLE001 - não pode derrubar a worker thread
            logger.exception("Erro inesperado em '%s' para '%s'", self._operation, self._name)
            self.signals.finished.emit(self._name, self._operation, False, str(exc), False)
            return

        message = _friendly_message(self._operation, result)
        logger.info(
            "Operação de configuração '%s' em '%s' -> sucesso=%s parcial=%s tempo=%.1fms",
            self._operation,
            self._name,
            result.success,
            result.partial,
            result.duration_ms,
        )
        if not result.success:
            logger.warning("Falha em '%s' para '%s': %s", self._operation, self._name, result.error)
        self.signals.finished.emit(self._name, self._operation, result.success, message, result.partial)


class _DetailsTask(QRunnable):
    """Busca a configuração atual de uma VPN (para pré-preencher o diálogo de edição)."""

    def __init__(self, manager: VpnConfigManager, name: str, all_users: bool) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self._manager = manager
        self._name = name
        self._all_users = all_users
        self.signals = _DetailsSignals()

    @Slot()
    def run(self) -> None:
        details = self._manager.get_details(self._name, self._all_users)
        self.signals.finished.emit(self._name, self._all_users, details)


def _friendly_message(operation: str, result: PsResult) -> str:
    if result.success:
        if result.partial:
            return {
                "add": "VPN criada, mas algumas rotas falharam ao ser aplicadas.",
                "update": "VPN atualizada, mas algumas rotas falharam ao ser aplicadas.",
            }.get(operation, "Operação concluída parcialmente.")
        return {
            "add": "VPN adicionada com sucesso.",
            "update": "VPN atualizada com sucesso.",
            "delete": "VPN excluída com sucesso.",
        }.get(operation, "Operação concluída.")
    if result.cancelled_by_user:
        return "Operação cancelada: permissão de administrador não concedida."
    verbs = {"add": "adicionar", "update": "atualizar", "delete": "excluir"}
    return f"Falha ao {verbs.get(operation, operation)}: {result.error or 'erro desconhecido'}"


class VpnConfigService(QObject):
    """Ponto único para adicionar/editar/excluir/consultar detalhes de VPN sem bloquear a UI.

    Usa um QThreadPool próprio (não o global do ConnectionService) para que uma
    solicitação de UAC pendente numa operação de escopo 'todos os usuários' não
    trave os botões de conectar/desconectar de outras VPNs.
    """

    operation_finished = Signal(str, str, bool, str, bool)  # name, operation, success, message, partial
    details_fetched = Signal(str, bool, object)  # name, all_users, Optional[VpnConnectionDetails]

    def __init__(self, manager: VpnConfigManager) -> None:
        super().__init__()
        self._manager = manager
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(2)

    def add(
        self, name: str, server: str, tunnel_type: str, all_users: bool, split_tunneling: bool, routes: List[str]
    ) -> None:
        self._submit_config(
            "add",
            name,
            dict(server=server, tunnel_type=tunnel_type, all_users=all_users, split_tunneling=split_tunneling, routes=routes),
        )

    def update(
        self, name: str, all_users: bool, server: str, tunnel_type: str, split_tunneling: bool, routes: List[str]
    ) -> None:
        self._submit_config(
            "update",
            name,
            dict(all_users=all_users, server=server, tunnel_type=tunnel_type, split_tunneling=split_tunneling, routes=routes),
        )

    def delete(self, name: str, all_users: bool) -> None:
        self._submit_config("delete", name, dict(all_users=all_users))

    def fetch_details(self, name: str, all_users: bool) -> None:
        task = _DetailsTask(self._manager, name, all_users)
        task.signals.finished.connect(self.details_fetched.emit)
        self._pool.start(task)

    def _submit_config(self, operation: str, name: str, kwargs: dict) -> None:
        task = _ConfigTask(self._manager, operation, name, kwargs)
        task.signals.finished.connect(self.operation_finished.emit)
        self._pool.start(task)
