"""Ponto de entrada da aplicação VPN Manager."""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.logger import setup_logging
from utils.single_instance import SingleInstanceGuard


def main() -> int:
    setup_logging(level=logging.INFO)
    logger = logging.getLogger("vpn_manager")
    logger.info("Iniciando VPN Manager")

    app = QApplication(sys.argv)
    app.setApplicationName("VPN Manager")
    app.setOrganizationName("VPNManager")
    app.setQuitOnLastWindowClosed(False)

    guard = SingleInstanceGuard()
    if not guard.try_acquire():
        logger.info("Outra instância do VPN Manager já está em execução; encerrando esta.")
        return 0

    window = MainWindow()
    guard.show_requested.connect(window.bring_to_foreground)
    start_minimized = (
        window.settings.start_with_windows
        and window.settings.start_minimized
        and window.tray_icon_available
    )
    if start_minimized:
        logger.info("Iniciando minimizado na bandeja (conforme configuração).")
    else:
        window.show()

    exit_code = app.exec()
    logger.info("VPN Manager encerrado (código %s)", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
