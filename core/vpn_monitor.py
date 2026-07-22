"""Serviço de monitoramento periódico do estado das VPNs, executado em uma QThread dedicada."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from core.models import VpnEntry, VpnStatus
from core.pbk_parser import PbkParser
from core.rasdial_manager import RasdialManager
from core.vpn_config_manager import VpnConfigManager

logger = logging.getLogger("vpn_manager.monitor")

# Intervalo mínimo entre consultas de IP interno para a mesma VPN conectada:
# evita spawnar powershell.exe a cada poll (que pode ser a cada 2s).
_IP_RECHECK_SECONDS = 30


class VpnMonitor(QObject):
    """Reavalia periodicamente os arquivos .pbk e as conexões ativas do rasdial.

    Deve ser movido para uma QThread própria (via moveToThread) antes de start()
    ser chamado, para não bloquear a interface gráfica.
    """

    vpns_updated = Signal(dict)  # Dict[str, VpnEntry]
    error_occurred = Signal(str)

    def __init__(
        self,
        pbk_parser: PbkParser,
        rasdial_manager: RasdialManager,
        interval_seconds: int = 5,
        vpn_config_manager: Optional[VpnConfigManager] = None,
    ) -> None:
        super().__init__()
        self._pbk_parser = pbk_parser
        self._rasdial_manager = rasdial_manager
        self._vpn_config_manager = vpn_config_manager
        self._interval_seconds = interval_seconds
        self._timer: Optional[QTimer] = None
        self._known_entries: Dict[str, VpnEntry] = {}
        self._last_ip_check: Dict[str, float] = {}

    @Slot()
    def start(self) -> None:
        """Inicia o temporizador de polling. Deve ser chamado de dentro da thread do monitor."""
        self._timer = QTimer()
        self._timer.setInterval(max(2, self._interval_seconds) * 1000)
        self._timer.timeout.connect(self.poll_once)
        self._timer.start()
        self.poll_once()

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    @Slot(int)
    def set_interval(self, seconds: int) -> None:
        self._interval_seconds = max(2, min(10, seconds))
        if self._timer is not None:
            self._timer.setInterval(self._interval_seconds * 1000)

    @Slot()
    def poll_once(self) -> None:
        """Executa uma rodada de leitura do .pbk e consulta ao rasdial, emitindo o resultado."""
        try:
            entries = self._pbk_parser.get_all_vpn_entries()
            active_result = self._rasdial_manager.list_active_connections()

            if not active_result.success:
                # rasdial falhou ao consultar conexões ativas (timeout, permissão, encoding,
                # servico RAS indisponível etc.). Sem essa informação não sabemos o estado real,
                # então preservamos o último estado conhecido em vez de marcar tudo como
                # desconectado — isso evitaria reconexão automática indevida e faria a UI
                # mostrar uma VPN ativa como caída só porque uma consulta falhou.
                logger.warning(
                    "Falha ao consultar conexões ativas (rc=%s): %s",
                    active_result.return_code,
                    active_result.stderr or active_result.stdout,
                )
                for key, entry in entries.items():
                    previous = self._known_entries.get(key)
                    if previous is not None:
                        entry.status = previous.status
                        entry.connected_since = previous.connected_since
                        entry.local_ip = previous.local_ip
                self._known_entries = entries
                self.vpns_updated.emit(entries)
                self.error_occurred.emit("Não foi possível consultar o estado das conexões VPN.")
                return

            active_names = {
                n.casefold() for n in self._rasdial_manager.parse_active_connections(active_result)
            }

            for key, entry in entries.items():
                previous = self._known_entries.get(key)
                is_active = entry.name.casefold() in active_names
                if is_active:
                    if previous is not None and previous.status == VpnStatus.CONNECTED:
                        entry.connected_since = previous.connected_since
                    else:
                        entry.connected_since = datetime.now()
                    entry.status = VpnStatus.CONNECTED
                    entry.local_ip = self._resolve_local_ip(key, entry, previous)
                else:
                    entry.status = VpnStatus.DISCONNECTED
                    entry.connected_since = None
                    entry.local_ip = ""
                    self._last_ip_check.pop(key, None)

            self._known_entries = entries
            self.vpns_updated.emit(entries)
        except Exception as exc:  # noqa: BLE001 - monitor não pode derrubar a thread
            logger.exception("Erro ao monitorar VPNs")
            self.error_occurred.emit(str(exc))

    def _resolve_local_ip(self, key: str, entry: VpnEntry, previous: Optional[VpnEntry]) -> str:
        """Consulta o IP interno apenas na transição para conectado e periodicamente depois."""
        carried_over = previous.local_ip if previous is not None else ""
        if self._vpn_config_manager is None:
            return carried_over

        now = time.monotonic()
        just_connected = previous is None or previous.status != VpnStatus.CONNECTED
        due_for_recheck = (now - self._last_ip_check.get(key, 0.0)) >= _IP_RECHECK_SECONDS
        if not just_connected and not due_for_recheck:
            return carried_over

        self._last_ip_check[key] = now
        try:
            ip = self._vpn_config_manager.get_local_ipv4(entry.name)
        except Exception:  # noqa: BLE001 - monitor não pode derrubar a thread
            logger.exception("Falha ao consultar IP interno de '%s'", entry.name)
            ip = None
        return ip or carried_over
