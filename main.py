"""Ponto de entrada da aplicação VPN Manager."""
from __future__ import annotations

import faulthandler
import logging
import sys
import threading

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from utils.constants import LOGS_DIR, migrate_portable_settings_if_needed
from utils.logger import setup_logging
from utils.single_instance import SingleInstanceGuard

# Mantido vivo pelo módulo: se for coletado pelo GC, faulthandler perde o arquivo.
_crash_file = None


def _enable_faulthandler() -> None:
    """Diagnostica crashes nativos (sem exceção Python) — ex.: violação de acesso
    dentro do Qt/PySide6, que não passa por sys.excepthook nem por qInstallMessageHandler.

    Registra, no momento da falha, o traceback Python de cada thread (o quadro
    exato onde cada uma estava parada) em logs/crash.log. É a última linha de
    defesa quando um crash não deixa nenhum rastro nos logs normais.
    """
    global _crash_file
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        _crash_file = open(LOGS_DIR / "crash.log", "a", encoding="utf-8")
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError:
        pass


class _NullStream:
    """Substitui sys.stdout/stderr quando ausentes (build --windowed do PyInstaller).

    Sem isto, qualquer print() ou exceção não tratada que chegue ao
    sys.excepthook padrão tenta escrever em None e levanta um AttributeError
    dentro do próprio tratamento de exceção — no limite entre Qt (C++) e Python,
    isso pode encerrar o processo inteiro sem deixar nenhum rastro no log.
    """

    def write(self, *_args, **_kwargs) -> None:
        pass

    def flush(self) -> None:
        pass


def _ensure_std_streams() -> None:
    if sys.stdout is None:
        sys.stdout = _NullStream()
    if sys.stderr is None:
        sys.stderr = _NullStream()


def _install_crash_logging(logger: logging.Logger) -> None:
    """Loga qualquer exceção não tratada (thread principal ou secundária) em vez
    de deixá-la se propagar de forma silenciosa e derrubar a aplicação."""

    def _log_unhandled(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Exceção não tratada na thread principal", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _log_unhandled

    def _log_unhandled_thread(args: "threading.ExceptHookArgs") -> None:
        logger.critical(
            "Exceção não tratada na thread '%s'",
            args.thread.name if args.thread else "desconhecida",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    threading.excepthook = _log_unhandled_thread

    _QT_LOG_FNS = {
        QtMsgType.QtDebugMsg: logger.debug,
        QtMsgType.QtInfoMsg: logger.info,
        QtMsgType.QtWarningMsg: logger.warning,
        QtMsgType.QtCriticalMsg: logger.error,
        QtMsgType.QtFatalMsg: logger.critical,
    }

    def _qt_message_handler(msg_type, context, message) -> None:
        _QT_LOG_FNS.get(msg_type, logger.info)("Qt: %s", message)

    qInstallMessageHandler(_qt_message_handler)


def main() -> int:
    _ensure_std_streams()
    migrate_portable_settings_if_needed()
    _enable_faulthandler()
    setup_logging(level=logging.INFO)
    logger = logging.getLogger("vpn_manager")
    _install_crash_logging(logger)
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
