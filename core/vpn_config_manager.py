"""Camada de alto nível para criar, editar e remover conexões VPN via PowerShell."""
from __future__ import annotations

import logging
from typing import List, Optional

from core.models import VpnConnectionDetails
from core.pbk_parser import PbkParser
from core.powershell_runner import PowerShellRunner, PsResult
from core.rasdial_manager import RasdialManager

logger = logging.getLogger("vpn_manager.vpnconfig")


class VpnConfigManager:
    """Cria/edita/remove conexões VPN via cmdlets do módulo PowerShell VpnClient."""

    def __init__(
        self,
        runner: PowerShellRunner,
        rasdial_manager: RasdialManager,
        pbk_parser: PbkParser,
    ) -> None:
        self._runner = runner
        self._rasdial_manager = rasdial_manager
        self._pbk_parser = pbk_parser

    def is_admin(self) -> bool:
        return self._runner.is_admin()

    def add(
        self,
        name: str,
        server: str,
        tunnel_type: str,
        all_users: bool,
        split_tunneling: bool,
        routes: List[str],
    ) -> PsResult:
        collision = self._find_cross_scope_collision(name, all_users)
        if collision is not None:
            scope_desc = "do usuário atual" if collision == "user" else "de todos os usuários"
            return PsResult(False, {}, f"Já existe uma VPN chamada '{name}' no escopo {scope_desc}. Escolha outro nome.")

        params = {
            "name": name,
            "server": server,
            "tunnel_type": tunnel_type,
            "all_users": all_users,
            "split_tunneling": split_tunneling,
            "routes": routes,
        }
        return self._runner.run("add_vpn.ps1", params, elevated=all_users)

    def update(
        self,
        name: str,
        all_users: bool,
        server: str,
        tunnel_type: str,
        split_tunneling: bool,
        routes: List[str],
    ) -> PsResult:
        self._disconnect_if_active(name)

        routes_to_add: List[str] = list(routes)
        routes_to_remove: List[str] = []
        if split_tunneling:
            current = self.get_details(name, all_users)
            existing = set(current.routes) if current else set()
            desired = set(routes)
            routes_to_add = sorted(desired - existing)
            routes_to_remove = sorted(existing - desired)

        params = {
            "name": name,
            "all_users": all_users,
            "server": server,
            "tunnel_type": tunnel_type,
            "split_tunneling": split_tunneling,
            "routes_to_add": routes_to_add,
            "routes_to_remove": routes_to_remove,
        }
        return self._runner.run("update_vpn.ps1", params, elevated=all_users)

    def delete(self, name: str, all_users: bool) -> PsResult:
        self._disconnect_if_active(name)
        return self._runner.run("remove_vpn.ps1", {"name": name, "all_users": all_users}, elevated=all_users)

    def get_details(self, name: str, all_users: bool) -> Optional[VpnConnectionDetails]:
        result = self._runner.run("get_vpn_details.ps1", {"name": name, "all_users": all_users}, elevated=False)
        if not result.success:
            logger.warning("Falha ao obter detalhes de '%s': %s", name, result.error)
            return None
        data = result.data
        return VpnConnectionDetails(
            name=name,
            scope="system" if all_users else "user",
            server=data.get("server", ""),
            tunnel_type=data.get("tunnel_type") or "Automatic",
            split_tunneling=bool(data.get("split_tunneling", False)),
            routes=list(data.get("routes") or []),
        )

    def get_local_ipv4(self, connection_name: str) -> Optional[str]:
        result = self._runner.run("get_local_ip.ps1", {"interface_alias": connection_name}, elevated=False)
        if not result.success:
            return None
        ip = result.data.get("ip")
        return ip or None

    def _disconnect_if_active(self, name: str) -> None:
        """Desconecta antes de editar/excluir: os cmdlets não são confiáveis numa conexão ativa."""
        active = self._rasdial_manager.parse_active_connections(self._rasdial_manager.list_active_connections())
        if name.casefold() in {n.casefold() for n in active}:
            self._rasdial_manager.disconnect(name)

    def _find_cross_scope_collision(self, name: str, all_users: bool) -> Optional[str]:
        """Verifica se já existe uma VPN com esse nome no OUTRO escopo (a UI mescla por nome)."""
        other_scope = "user" if all_users else "system"
        entries = self._pbk_parser.get_all_vpn_entries()
        entry = entries.get(name.casefold())
        if entry is not None and entry.scope == other_scope:
            return other_scope
        return None
