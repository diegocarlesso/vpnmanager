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

# Espelha _DARK_QSS com cores claras. Precisa existir explicitamente: no
# Windows com modo escuro do sistema ativado (Configurações > Personalização >
# Cores > "Escuro"), o Qt6 detecta o tema do SO e já aplica uma palette padrão
# escura antes mesmo de qualquer folha de estilo nossa. Uma string vazia
# ("resetar para o padrão") nesse caso continua escura — por isso trocar para
# "light" não tinha efeito visível nenhum. "light" precisa forçar cores claras
# tão explicitamente quanto "dark" força cores escuras.
_LIGHT_QSS = """
QWidget {
    background-color: #f5f5f5;
    color: #202020;
    selection-background-color: #3c6bd6;
    selection-color: #ffffff;
}
QMainWindow, QDialog {
    background-color: #f5f5f5;
}
QToolBar {
    background-color: #e8e8e8;
    border: none;
    spacing: 4px;
}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #ffffff;
    color: #202020;
    border: 1px solid #c0c0c0;
    border-radius: 3px;
    padding: 3px;
}
QComboBox QAbstractItemView {
    background-color: #ffffff;
    color: #202020;
    selection-background-color: #3c6bd6;
    selection-color: #ffffff;
}
QPushButton {
    background-color: #e8e8e8;
    color: #202020;
    border: 1px solid #c0c0c0;
    border-radius: 3px;
    padding: 4px 12px;
}
QPushButton:hover {
    background-color: #dcdcdc;
}
QPushButton:pressed {
    background-color: #cfcfcf;
}
QPushButton:disabled {
    color: #a0a0a0;
    background-color: #eeeeee;
}
QFrame#VpnWidget {
    background-color: #ffffff;
    border: 1px solid #d0d0d0;
    border-radius: 4px;
}
QScrollArea {
    background-color: #f5f5f5;
    border: none;
}
QStatusBar {
    background-color: #e8e8e8;
    color: #303030;
}
QMenu {
    background-color: #ffffff;
    color: #202020;
    border: 1px solid #c0c0c0;
}
QMenu::item:selected {
    background-color: #3c6bd6;
    color: #ffffff;
}
QCheckBox, QRadioButton, QLabel {
    color: #202020;
}
QMessageBox {
    background-color: #f5f5f5;
}
"""


def apply_theme(theme: str) -> None:
    """Aplica o tema ("light" ou "dark") a toda a aplicação em execução.

    Ambos os temas usam uma folha de estilo explícita — nenhum dos dois
    depende do tema do Windows (claro/escuro) como base, para que a escolha na
    tela de Configurações sempre tenha efeito visível, independentemente de
    como o sistema operacional está configurado. "dark" é o padrão para
    qualquer valor que não seja "light", já que essas são as duas únicas
    opções oferecidas em Configurações.
    """
    app = QApplication.instance()
    if app is None:
        return
    app.setStyleSheet(_LIGHT_QSS if theme == "light" else _DARK_QSS)
