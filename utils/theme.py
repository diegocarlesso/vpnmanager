"""Aplicação do tema claro/escuro à aplicação inteira via folha de estilo Qt."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

_DARK_QSS = """
QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    selection-background-color: #3c6bd6;
}
QMainWindow, QDialog {
    background-color: #1e1e1e;
}
QToolBar {
    background-color: #252526;
    border: none;
    spacing: 4px;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    border-radius: 3px;
    padding: 3px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e0e0e0;
    selection-background-color: #3c6bd6;
}
QPushButton {
    background-color: #3c3c3c;
    color: #e0e0e0;
    border: 1px solid #4a4a4a;
    border-radius: 3px;
    padding: 4px 12px;
}
QPushButton:hover {
    background-color: #4a4a4a;
}
QPushButton:pressed {
    background-color: #555555;
}
QPushButton:disabled {
    color: #7a7a7a;
    background-color: #333333;
}
QFrame#VpnWidget {
    background-color: #2a2a2a;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
}
QScrollArea {
    background-color: #1e1e1e;
    border: none;
}
QStatusBar {
    background-color: #252526;
    color: #cfcfcf;
}
QMenu {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
}
QMenu::item:selected {
    background-color: #3c6bd6;
}
QCheckBox, QRadioButton, QLabel {
    color: #e0e0e0;
}
QMessageBox {
    background-color: #1e1e1e;
}
"""


def apply_theme(theme: str) -> None:
    """Aplica o tema ("light" ou "dark") a toda a aplicação em execução.

    "light" reseta para a folha de estilo padrão da plataforma (string vazia);
    qualquer outro valor cai em "dark", já que são as duas únicas opções
    oferecidas em Configurações.
    """
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(_DARK_QSS if theme == "dark" else "")
