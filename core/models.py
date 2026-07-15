"""Modelos de dados utilizados em toda a aplicação."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class VpnStatus(Enum):
    """Estados possíveis de uma conexão VPN."""

    DISCONNECTED = "Desconectado"
    CONNECTING = "Conectando"
    CONNECTED = "Conectado"
    DISCONNECTING = "Desconectando"
    ERROR = "Erro"


@dataclass
class VpnEntry:
    """Representa uma entrada de VPN lida do arquivo .pbk, combinada com seu estado atual."""

    name: str
    server: str = ""
    phone_number: str = ""
    device: str = ""
    conn_type: str = ""
    has_saved_credentials: bool = False
    status: VpnStatus = VpnStatus.DISCONNECTED
    connected_since: Optional[datetime] = None
    last_error: str = ""
    is_favorite: bool = False
    scope: str = "user"  # "user" (USER_PBK_PATH) ou "system" (SYSTEM_PBK_PATH)
    local_ip: str = ""

    @property
    def uptime_seconds(self) -> int:
        """Segundos desde que a conexão foi estabelecida, ou 0 se não estiver conectada."""
        if self.connected_since is None:
            return 0
        return int((datetime.now() - self.connected_since).total_seconds())

    def key(self) -> str:
        """Chave normalizada (case-insensitive) usada para indexação em dicionários."""
        return self.name.casefold()


@dataclass
class VpnConnectionDetails:
    """Configuração completa de uma VPN, obtida sob demanda via PowerShell para edição."""

    name: str
    scope: str  # "user" | "system"
    server: str
    tunnel_type: str  # "Automatic" | "Pptp" | "L2tp" | "Sstp" | "Ikev2"
    split_tunneling: bool  # True = apenas as rotas da lista; False = rota padrão (todo tráfego)
    routes: List[str] = field(default_factory=list)


@dataclass
class LogRecordEntry:
    """Registro estruturado de uma operação executada, usado no painel de logs."""

    timestamp: datetime
    vpn_name: str
    operation: str
    duration_ms: float
    success: bool
    message: str = ""
