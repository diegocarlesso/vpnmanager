"""Diálogo para editar a lista de rotas (blocos CIDR) de uma VPN com split tunneling."""
from __future__ import annotations

import ipaddress
from typing import List

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)

_DEFAULT_ROUTE_NETS = {"0.0.0.0/0", "::/0"}


class RouteListDialog(QDialog):
    """Pequena janela com os blocos de IP (CIDR) que devem ser roteados pela VPN.

    As rotas só são efetivamente aplicadas quando o diálogo de edição da VPN
    (que abre este) é salvo — este diálogo apenas mantém a lista em memória.
    """

    def __init__(self, routes: List[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rotas da VPN")
        self.setMinimumWidth(420)
        self._routes: List[str] = list(routes)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        hint = QLabel(
            "Blocos de IP/CIDR que devem ser roteados pela VPN, separados por vírgula ou "
            "quebra de linha.\nEx.: 10.0.0.0/24, 192.168.1.0/24",
            self,
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._text_edit = QPlainTextEdit(self)
        self._text_edit.setPlainText(", ".join(self._routes))
        self._text_edit.setPlaceholderText("10.0.0.0/24, 192.168.1.0/24")
        layout.addWidget(self._text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:  # noqa: N802 - assinatura definida pelo Qt
        raw = self._text_edit.toPlainText()
        tokens = [token.strip() for line in raw.split("\n") for token in line.split(",")]
        tokens = [token for token in tokens if token]

        networks: List[str] = []
        seen = set()
        for token in tokens:
            try:
                network = ipaddress.ip_network(token, strict=False)
            except ValueError:
                QMessageBox.warning(self, "Rota inválida", f"'{token}' não é um bloco de IP/CIDR válido.")
                return
            canonical = str(network)
            if canonical in _DEFAULT_ROUTE_NETS:
                QMessageBox.warning(
                    self,
                    "Rota não permitida",
                    "Para rotear todo o tráfego pela VPN, use a opção 'Rota padrão' em vez de "
                    f"adicionar '{canonical}' como rota.",
                )
                return
            if canonical not in seen:
                seen.add(canonical)
                networks.append(canonical)

        self._routes = networks
        super().accept()

    def result_routes(self) -> List[str]:
        return list(self._routes)
