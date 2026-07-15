"""Serviço de notificações discretas via bandeja do sistema."""
from __future__ import annotations

from PySide6.QtWidgets import QSystemTrayIcon


class NotificationService:
    """Encapsula o disparo de notificações do QSystemTrayIcon."""

    def __init__(self, tray_icon: QSystemTrayIcon) -> None:
        self._tray_icon = tray_icon

    def notify(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information,
        timeout_ms: int = 4000,
    ) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable() and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, icon, timeout_ms)
