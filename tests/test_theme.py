"""Testes de utils.theme: light e dark precisam ser visivelmente distintos.

Regressão do bug relatado em produção: no Windows com o modo escuro do sistema
ativado, o Qt6 já aplica uma palette escura por padrão antes de qualquer
folha de estilo nossa. apply_theme("light") limpava a folha de estilo (string
vazia) esperando "resetar para o padrão", mas nesse cenário o padrão também é
escuro — então trocar para "light" não tinha nenhum efeito visível. A correção
usa uma folha de estilo clara explícita em vez de depender do padrão do Qt/SO.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QPushButton

from utils.theme import apply_theme


def _button_background(app: QApplication) -> str:
    btn = QPushButton("teste")
    btn.ensurePolished()
    return btn.palette().button().color().name()


def test_light_and_dark_produce_different_stylesheets(qt_application: QApplication) -> None:
    apply_theme("light")
    light_stylesheet = qt_application.styleSheet()

    apply_theme("dark")
    dark_stylesheet = qt_application.styleSheet()

    assert light_stylesheet != dark_stylesheet
    assert light_stylesheet.strip() != ""  # não pode ser "resetar para o padrão"
    assert dark_stylesheet.strip() != ""


def test_light_theme_forces_light_button_background(qt_application: QApplication) -> None:
    apply_theme("light")
    color = _button_background(qt_application)
    # Fundo claro: os três canais RGB devem estar altos (não é um valor exato
    # de pixel que importa, e sim que não seja uma cor escura).
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    assert min(r, g, b) > 180, f"fundo do botão deveria ser claro, veio {color}"


def test_dark_theme_forces_dark_button_background(qt_application: QApplication) -> None:
    apply_theme("dark")
    color = _button_background(qt_application)
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    assert max(r, g, b) < 100, f"fundo do botão deveria ser escuro, veio {color}"


def test_switching_back_to_light_after_dark_restores_light_appearance(qt_application: QApplication) -> None:
    apply_theme("dark")
    apply_theme("light")
    color = _button_background(qt_application)
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    assert min(r, g, b) > 180, f"fundo do botão deveria voltar a ser claro, veio {color}"
