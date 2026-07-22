"""Fixtures compartilhadas por toda a suíte.

Uma única QApplication para toda a sessão de testes: ter uma QCoreApplication
e uma QApplication coexistindo no mesmo processo (ex.: um arquivo de teste
criando cada uma) derruba o Qt em nível nativo sem traceback Python. QApplication
é superconjunto de QCoreApplication, então serve para testes que só usam sinais
de QObject e para os que precisam de widgets reais (MainWindow).
"""
from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    app = QApplication.instance() or QApplication([])
    yield app
