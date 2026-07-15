"""Configuração central de logging da aplicação."""
from __future__ import annotations

import logging
import logging.handlers
from datetime import date

from utils.constants import LOGS_DIR

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def _log_filename() -> str:
    return f"vpn-manager-{date.today().isoformat()}.log"


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura o logger raiz da aplicação com rotação por tamanho e arquivo diário.

    O nome do arquivo muda a cada dia (vpn-manager-YYYY-MM-DD.log); dentro de um
    mesmo dia, o RotatingFileHandler mantém o arquivo sob controle de tamanho.
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / _log_filename()

    root_logger = logging.getLogger("vpn_manager")
    root_logger.setLevel(level)
    root_logger.propagate = False

    if root_logger.handlers:
        return root_logger

    formatter = logging.Formatter(_LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=7, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    return root_logger
