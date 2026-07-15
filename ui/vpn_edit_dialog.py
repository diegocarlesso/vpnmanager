"""Diálogo de Adicionar/Editar uma conexão VPN."""
from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from core.models import VpnConnectionDetails
from ui.route_list_dialog import RouteListDialog

_TUNNEL_TYPES = ["Automatic", "Pptp", "L2tp", "Sstp", "Ikev2"]


class VpnEditDialog(QDialog):
    """Formulário usado tanto para adicionar quanto para editar uma VPN.

    Quando `details` é None, o diálogo abre em modo de criação (todos os campos
    editáveis). Quando `details` é fornecido, abre em modo de edição: Nome e
    Escopo ficam travados, pois o Windows não permite renomear uma conexão nem
    migrar seu escopo via Set-VpnConnection — isso exigiria excluir e recriar.
    """

    def __init__(
        self,
        details: Optional[VpnConnectionDetails],
        is_admin: bool,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._is_edit = details is not None
        self._is_admin = is_admin
        self._routes: List[str] = list(details.routes) if details is not None else []
        self.setWindowTitle("Editar VPN" if self._is_edit else "Adicionar VPN")
        self.setMinimumWidth(420)
        self._build_ui()
        if details is not None:
            self._populate(details)
        self._update_routes_button()
        self._update_uac_hint()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name_edit = QLineEdit(self)
        self._name_edit.setEnabled(not self._is_edit)
        form.addRow("Nome:", self._name_edit)

        self._server_edit = QLineEdit(self)
        form.addRow("Servidor:", self._server_edit)

        self._tunnel_combo = QComboBox(self)
        self._tunnel_combo.addItems(_TUNNEL_TYPES)
        form.addRow("Tipo de túnel:", self._tunnel_combo)

        self._user_radio = QRadioButton("Somente eu", self)
        self._system_radio = QRadioButton("Todos os usuários (requer administrador)", self)
        self._user_radio.setChecked(True)
        self._scope_group = QButtonGroup(self)
        self._scope_group.addButton(self._user_radio)
        self._scope_group.addButton(self._system_radio)
        self._user_radio.setEnabled(not self._is_edit)
        self._system_radio.setEnabled(not self._is_edit)
        self._system_radio.toggled.connect(self._update_uac_hint)
        form.addRow("Escopo:", self._user_radio)
        form.addRow("", self._system_radio)

        self._uac_hint = QLabel(
            "Uma solicitação de administrador (UAC) aparecerá ao salvar.", self
        )
        self._uac_hint.setStyleSheet("color: #b26a00;")
        self._uac_hint.setWordWrap(True)
        form.addRow("", self._uac_hint)

        self._default_route_check = QCheckBox("Rota padrão (todo tráfego pela VPN)", self)
        self._default_route_check.setChecked(True)
        self._default_route_check.toggled.connect(self._update_routes_button)
        form.addRow(self._default_route_check)

        self._routes_btn = QPushButton(self)
        self._routes_btn.clicked.connect(self._open_route_dialog)
        form.addRow("", self._routes_btn)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, details: VpnConnectionDetails) -> None:
        self._name_edit.setText(details.name)
        self._server_edit.setText(details.server)
        index = self._tunnel_combo.findText(details.tunnel_type)
        if index >= 0:
            self._tunnel_combo.setCurrentIndex(index)
        if details.scope == "system":
            self._system_radio.setChecked(True)
        else:
            self._user_radio.setChecked(True)
        self._default_route_check.setChecked(not details.split_tunneling)

    def _update_routes_button(self) -> None:
        split_tunneling = not self._default_route_check.isChecked()
        self._routes_btn.setEnabled(split_tunneling)
        self._routes_btn.setText(f"Editar rotas ({len(self._routes)})…")

    def _update_uac_hint(self) -> None:
        self._uac_hint.setVisible(self._system_radio.isChecked() and not self._is_admin)

    def _open_route_dialog(self) -> None:
        dialog = RouteListDialog(self._routes, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._routes = dialog.result_routes()
            self._update_routes_button()

    def accept(self) -> None:  # noqa: N802 - assinatura definida pelo Qt
        name = self._name_edit.text().strip()
        server = self._server_edit.text().strip()
        if not name or not server:
            QMessageBox.warning(self, "Campos obrigatórios", "Informe o nome e o servidor da VPN.")
            return

        split_tunneling = not self._default_route_check.isChecked()
        if split_tunneling and not self._routes:
            proceed = QMessageBox.question(
                self,
                "Nenhuma rota definida",
                "Rota padrão está desmarcada, mas nenhum bloco de IP foi adicionado — "
                "praticamente nada será roteado pela VPN. Salvar mesmo assim?",
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        super().accept()

    def result(self) -> Dict[str, object]:
        return {
            "name": self._name_edit.text().strip(),
            "server": self._server_edit.text().strip(),
            "tunnel_type": self._tunnel_combo.currentText(),
            "all_users": self._system_radio.isChecked(),
            "split_tunneling": not self._default_route_check.isChecked(),
            "routes": list(self._routes),
        }
