"""Leitura e interpretação de arquivos .pbk (phonebook) do Windows RAS."""
from __future__ import annotations

import configparser
import logging
from pathlib import Path
from typing import Dict, List, Optional

from core.models import VpnEntry, VpnStatus
from utils.constants import SYSTEM_PBK_PATH, USER_PBK_PATH

logger = logging.getLogger("vpn_manager.pbk")

_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


class PbkParser:
    """Localiza e interpreta os arquivos rasphone.pbk do usuário e do sistema."""

    def __init__(self, custom_directory: Optional[str] = None) -> None:
        self._custom_directory = Path(custom_directory) if custom_directory else None

    def set_custom_directory(self, custom_directory: Optional[str]) -> None:
        """Substitui a busca padrão por um diretório PBK definido pelo usuário."""
        self._custom_directory = Path(custom_directory) if custom_directory else None

    def get_pbk_paths(self) -> List[Path]:
        """Retorna os caminhos de arquivos .pbk existentes a serem lidos."""
        if self._custom_directory:
            candidate = self._custom_directory / "rasphone.pbk"
            return [candidate] if candidate.exists() else []
        return [p for p in (USER_PBK_PATH, SYSTEM_PBK_PATH) if p.exists()]

    def get_last_modified(self) -> float:
        """Timestamp de modificação mais recente entre os arquivos monitorados."""
        latest = 0.0
        for path in self.get_pbk_paths():
            try:
                latest = max(latest, path.stat().st_mtime)
            except OSError:
                continue
        return latest

    def get_all_vpn_entries(self) -> Dict[str, VpnEntry]:
        """Combina as entradas de todos os arquivos .pbk encontrados, indexadas por escopo+nome."""
        entries: Dict[str, VpnEntry] = {}
        for path in self.get_pbk_paths():
            for entry in self.parse_pbk_file(path):
                entries[entry.key()] = entry

        name_counts: Dict[str, int] = {}
        for entry in entries.values():
            folded = entry.name.casefold()
            name_counts[folded] = name_counts.get(folded, 0) + 1
        for entry in entries.values():
            entry.duplicate_name = name_counts[entry.name.casefold()] > 1

        return entries

    def _scope_for_path(self, path: Path) -> str:
        """Determina o escopo ("user"/"system") de um arquivo .pbk pela sua origem.

        Só é significativo quando nenhum diretório customizado foi definido, já que
        um diretório customizado não tem correspondência com os cmdlets de VPN do
        Windows (que sempre operam sobre os phonebooks reais de usuário/sistema).
        """
        if self._custom_directory:
            return "user"
        try:
            return "system" if path.resolve() == SYSTEM_PBK_PATH.resolve() else "user"
        except OSError:
            return "user"

    def parse_pbk_file(self, path: Path) -> List[VpnEntry]:
        """Interpreta um único arquivo .pbk e retorna as entradas de VPN nele contidas."""
        text = self._read_text(path)
        if text is None:
            return []

        parser = configparser.ConfigParser(strict=False, interpolation=None)
        try:
            parser.read_string(text)
        except configparser.Error as exc:
            logger.error("Erro ao interpretar %s: %s", path, exc)
            return []

        scope = self._scope_for_path(path)
        entries: List[VpnEntry] = []
        for section in parser.sections():
            data = parser[section]
            server = data.get("phonenumber", "").strip()
            device = data.get("device", "").strip()
            conn_type = self._infer_connection_type(data)
            entries.append(
                VpnEntry(
                    name=section,
                    server=server,
                    phone_number=server,
                    device=device,
                    conn_type=conn_type,
                    status=VpnStatus.DISCONNECTED,
                    scope=scope,
                    phonebook_path=str(path),
                )
            )
        return entries

    @staticmethod
    def _infer_connection_type(data: "configparser.SectionProxy") -> str:
        media = data.get("media", "").strip().lower()
        vpn_strategy = data.get("vpnstrategy", "").strip()
        if "rastapi" in media or vpn_strategy:
            return "VPN"
        if media:
            return media.upper()
        return "VPN"

    @staticmethod
    def _read_text(path: Path) -> Optional[str]:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            logger.error("Não foi possível ler %s: %s", path, exc)
            return None
        for encoding in _ENCODINGS:
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        logger.error("Falha ao decodificar %s com codificações conhecidas", path)
        return None
