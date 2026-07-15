"""Diálogo para solicitar usuário/senha de uma VPN, com opção de salvá-los com segurança."""
from __future__ import annotations

from typing import Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class CredentialsDialog(QDialog):
    """Formulário de usuário/senha exibido quando uma VPN exige autenticação.

    O checkbox "lembrar" fica marcado por padrão: a maioria dos clientes VPN
    corporativos salva as credenciais após a primeira conexão bem-sucedida,
    evitando pedir novamente a cada clique em "Conectar".
    """

    def __init__(self, vpn_name: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Credenciais — {vpn_name}")
        self.setMinimumWidth(340)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._username_edit = QLineEdit(self)
        form.addRow("Usuário:", self._username_edit)

        self._password_edit = QLineEdit(self)
        self._password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Senha:", self._password_edit)

        layout.addLayout(form)

        self._remember_check = QCheckBox("Salvar minhas credenciais neste computador", self)
        self._remember_check.setChecked(True)
        layout.addWidget(self._remember_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._username_edit.setFocus()

    def _on_accept(self) -> None:
        if self._username_edit.text().strip():
            self.accept()

    def result_credentials(self) -> Tuple[str, str, bool]:
        return (
            self._username_edit.text().strip(),
            self._password_edit.text(),
            self._remember_check.isChecked(),
        )
