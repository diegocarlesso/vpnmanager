"""Funções utilitárias diversas: formatação, sanitização e geração de ícones."""
from __future__ import annotations

from datetime import timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap

from utils.constants import ASSETS_DIR


def format_duration(total_seconds: int) -> str:
    """Formata um total de segundos como HH:MM:SS."""
    if total_seconds <= 0:
        return "00:00:00"
    delta = timedelta(seconds=total_seconds)
    hours, remainder = divmod(delta.seconds + delta.days * 86400, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def sanitize_for_log(text: str) -> str:
    """Remove quebras de linha e espaços supérfluos para manter o log em uma linha."""
    return text.replace("\r", " ").replace("\n", " ").strip()


def truncate(text: str, max_length: int = 60) -> str:
    return text if len(text) <= max_length else text[: max_length - 1] + "…"


def create_app_icon(color: str = "#1565c0", size: int = 64) -> QIcon:
    """Gera um ícone simples em tempo de execução, sem depender de arquivos externos."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, size - 8, size - 8)

    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(int(size * 0.4))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "V")
    painter.end()

    return QIcon(pixmap)


def load_app_icon() -> QIcon:
    """Carrega o ícone da aplicação a partir de assets/icon.png, se existir.

    Cai de volta para o ícone gerado programaticamente caso o arquivo não
    exista ou não possa ser lido, garantindo que a aplicação sempre tenha
    um ícone válido.
    """
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
    return create_app_icon()
