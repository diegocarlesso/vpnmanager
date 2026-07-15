"""Janela de visualização de logs e diagnóstico."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from utils.constants import LOGS_DIR


class LogWindow(QDialog):
    """Exibe o conteúdo do log do dia corrente, com atualização automática e exportação."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Logs e Diagnóstico")
        self.resize(760, 480)
        self._log_path = self._current_log_path()
        self._last_size = -1
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh(force=True)

    @staticmethod
    def _current_log_path() -> Path:
        return LOGS_DIR / f"vpn-manager-{date.today().isoformat()}.log"

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        self._path_label = QLabel(str(self._log_path), self)
        self._path_label.setStyleSheet("color: #666;")
        layout.addWidget(self._path_label)

        self._text_edit = QPlainTextEdit(self)
        self._text_edit.setReadOnly(True)
        self._text_edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._text_edit)

        buttons = QHBoxLayout()
        refresh_btn = QPushButton("Atualizar", self)
        refresh_btn.clicked.connect(lambda: self._refresh(force=True))
        export_btn = QPushButton("Exportar…", self)
        export_btn.clicked.connect(self._export)
        buttons.addWidget(refresh_btn)
        buttons.addWidget(export_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _refresh(self, force: bool = False) -> None:
        self._log_path = self._current_log_path()
        self._path_label.setText(str(self._log_path))
        if not self._log_path.exists():
            return
        try:
            size = self._log_path.stat().st_size
            if not force and size == self._last_size:
                return
            content = self._log_path.read_text(encoding="utf-8", errors="replace")
            self._last_size = size
            scrollbar = self._text_edit.verticalScrollBar()
            at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
            self._text_edit.setPlainText(content)
            if at_bottom or force:
                scrollbar.setValue(scrollbar.maximum())
        except OSError:
            pass

    def _export(self) -> None:
        if not self._log_path.exists():
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Exportar log", self._log_path.name, "Arquivos de log (*.log);;Todos os arquivos (*.*)"
        )
        if destination:
            shutil.copyfile(self._log_path, destination)
