"""Diálogo de configurações da aplicação."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from core.settings import AppSettings


class SettingsDialog(QDialog):
    """Permite editar as preferências persistidas em config/settings.json."""

    def __init__(self, settings: AppSettings, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(440)
        self._settings = settings
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._refresh_spin = QSpinBox(self)
        self._refresh_spin.setRange(2, 10)
        self._refresh_spin.setSuffix(" s")
        self._refresh_spin.setValue(self._settings.refresh_interval)
        form.addRow("Intervalo de atualização:", self._refresh_spin)

        self._timeout_spin = QSpinBox(self)
        self._timeout_spin.setRange(5, 120)
        self._timeout_spin.setSuffix(" s")
        self._timeout_spin.setValue(self._settings.command_timeout)
        form.addRow("Timeout dos comandos:", self._timeout_spin)

        self._startup_check = QCheckBox("Iniciar com o Windows", self)
        self._startup_check.setChecked(self._settings.start_with_windows)
        self._startup_check.toggled.connect(self._update_start_minimized_enabled)
        form.addRow(self._startup_check)

        self._start_minimized_check = QCheckBox("Iniciar minimizado na bandeja", self)
        self._start_minimized_check.setChecked(self._settings.start_minimized)
        form.addRow(self._start_minimized_check)
        self._update_start_minimized_enabled()

        self._tray_check = QCheckBox("Minimizar para a bandeja do sistema ao fechar", self)
        self._tray_check.setChecked(self._settings.minimize_to_tray)
        form.addRow(self._tray_check)

        self._reconnect_check = QCheckBox("Reconexão automática em caso de queda", self)
        self._reconnect_check.setChecked(self._settings.auto_reconnect)
        form.addRow(self._reconnect_check)

        self._theme_combo = QComboBox(self)
        self._theme_combo.addItems(["light", "dark"])
        self._theme_combo.setCurrentText(self._settings.theme)
        form.addRow("Tema:", self._theme_combo)

        pbk_row = QHBoxLayout()
        self._pbk_edit = QLineEdit(self._settings.pbk_directory or "", self)
        self._pbk_browse_btn = QPushButton("Procurar…", self)
        self._pbk_browse_btn.clicked.connect(self._browse_pbk_directory)
        pbk_row.addWidget(self._pbk_edit)
        pbk_row.addWidget(self._pbk_browse_btn)
        form.addRow("Diretório PBK personalizado:", pbk_row)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _update_start_minimized_enabled(self) -> None:
        enabled = self._startup_check.isChecked()
        self._start_minimized_check.setEnabled(enabled)
        if not enabled:
            self._start_minimized_check.setChecked(False)

    def _browse_pbk_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Selecionar diretório PBK")
        if directory:
            self._pbk_edit.setText(directory)

    def result_settings(self) -> AppSettings:
        """Constrói um novo AppSettings a partir dos valores escolhidos no diálogo."""
        return AppSettings(
            refresh_interval=self._refresh_spin.value(),
            start_with_windows=self._startup_check.isChecked(),
            theme=self._theme_combo.currentText(),
            favorite_vpn=self._settings.favorite_vpn,
            command_timeout=self._timeout_spin.value(),
            pbk_directory=self._pbk_edit.text().strip() or None,
            minimize_to_tray=self._tray_check.isChecked(),
            auto_reconnect=self._reconnect_check.isChecked(),
            start_minimized=self._start_minimized_check.isChecked(),
        )
