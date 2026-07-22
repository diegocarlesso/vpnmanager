"""Widget de cartão representando uma única conexão VPN na lista principal."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from core.models import VpnEntry, VpnStatus
from utils.helpers import format_duration

_STATUS_COLORS = {
    VpnStatus.CONNECTED: QColor("#2e7d32"),
    VpnStatus.CONNECTING: QColor("#f9a825"),
    VpnStatus.DISCONNECTING: QColor("#f9a825"),
    VpnStatus.DISCONNECTED: QColor("#9e9e9e"),
    VpnStatus.ERROR: QColor("#c62828"),
}


class _StatusDot(QLabel):
    """Indicador visual simples (círculo colorido) do estado atual da VPN."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = _STATUS_COLORS[VpnStatus.DISCONNECTED]

    def set_status(self, status: VpnStatus) -> None:
        self._color = _STATUS_COLORS.get(status, _STATUS_COLORS[VpnStatus.DISCONNECTED])
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - assinatura definida pelo Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 12, 12)


class VpnWidget(QFrame):
    """Cartão exibindo nome, servidor, status, tempo conectado e ações de uma VPN."""

    connect_requested = Signal(str)
    disconnect_requested = Signal(str)
    reconnect_requested = Signal(str)
    cancel_requested = Signal(str)
    favorite_toggled = Signal(str)
    edit_requested = Signal(str)
    delete_requested = Signal(str)
    forget_credentials_requested = Signal(str)

    def __init__(self, entry: VpnEntry, can_edit: bool = True, parent=None) -> None:
        super().__init__(parent)
        self._entry = entry
        self._can_edit = can_edit
        self._busy = False
        self.setObjectName("VpnWidget")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._build_ui()

        self._uptime_timer = QTimer(self)
        self._uptime_timer.setInterval(1000)
        self._uptime_timer.timeout.connect(self._refresh_uptime)
        self._uptime_timer.start()

        self.update_entry(entry)

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)

        self._status_dot = _StatusDot(self)
        root.addWidget(self._status_dot)

        info_layout = QVBoxLayout()
        self._name_label = QLabel(self)
        self._name_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._server_label = QLabel(self)
        self._server_label.setStyleSheet("color: #666;")
        self._ip_label = QLabel(self)
        self._ip_label.setStyleSheet("color: #666; font-size: 11px;")
        info_layout.addWidget(self._name_label)
        info_layout.addWidget(self._server_label)
        info_layout.addWidget(self._ip_label)
        root.addLayout(info_layout, stretch=1)

        self._status_label = QLabel(self)
        self._status_label.setMinimumWidth(110)
        root.addWidget(self._status_label)

        self._uptime_label = QLabel(self)
        self._uptime_label.setMinimumWidth(80)
        self._uptime_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._uptime_label)

        self._connect_btn = QPushButton("Conectar", self)
        self._disconnect_btn = QPushButton("Desconectar", self)
        self._reconnect_btn = QPushButton("Reconectar", self)
        self._cancel_btn = QPushButton("Cancelar", self)
        for btn in (self._connect_btn, self._disconnect_btn, self._reconnect_btn, self._cancel_btn):
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self._connect_btn.clicked.connect(lambda: self.connect_requested.emit(self._entry.key()))
        self._disconnect_btn.clicked.connect(lambda: self.disconnect_requested.emit(self._entry.key()))
        self._reconnect_btn.clicked.connect(lambda: self.reconnect_requested.emit(self._entry.key()))
        self._cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self._entry.key()))

        root.addWidget(self._connect_btn)
        root.addWidget(self._disconnect_btn)
        root.addWidget(self._reconnect_btn)
        root.addWidget(self._cancel_btn)
        self._cancel_btn.setVisible(False)

        self._menu_btn = QPushButton("⋮", self)
        self._menu_btn.setFixedWidth(28)
        self._menu_btn.clicked.connect(self._show_menu)
        root.addWidget(self._menu_btn)

    def _show_menu(self) -> None:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        fav_text = "Remover dos favoritos" if self._entry.is_favorite else "Marcar como favorita"
        fav_action = menu.addAction(fav_text)
        fav_action.triggered.connect(lambda: self.favorite_toggled.emit(self._entry.key()))

        if self._entry.has_saved_credentials:
            forget_action = menu.addAction("Esquecer credenciais salvas")
            forget_action.triggered.connect(lambda: self.forget_credentials_requested.emit(self._entry.key()))

        menu.addSeparator()
        edit_action = menu.addAction("Editar…")
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self._entry.key()))
        delete_action = menu.addAction("Excluir…")
        delete_action.triggered.connect(self._confirm_delete)
        if not self._can_edit:
            tooltip = "Indisponível com diretório PBK personalizado nas configurações."
            edit_action.setEnabled(False)
            edit_action.setToolTip(tooltip)
            delete_action.setEnabled(False)
            delete_action.setToolTip(tooltip)

        menu.exec(self._menu_btn.mapToGlobal(self._menu_btn.rect().bottomLeft()))

    def _confirm_delete(self) -> None:
        answer = QMessageBox.question(
            self,
            "Excluir VPN",
            f"Excluir a conexão VPN '{self._entry.name}'? Essa ação não pode ser desfeita.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.delete_requested.emit(self._entry.key())

    def update_entry(self, entry: VpnEntry) -> None:
        """Atualiza o conteúdo visual do cartão a partir de um VpnEntry atualizado."""
        self._entry = entry
        label = entry.name
        if entry.duplicate_name:
            # Mesmo nome existe em outro escopo (usuário/sistema): sem isso, os dois
            # cartões seriam indistinguíveis na tela.
            scope_label = "sistema" if entry.scope == "system" else "usuário"
            label = f"{entry.name} ({scope_label})"
        self._name_label.setText(label + (" ★" if entry.is_favorite else ""))
        self._server_label.setText(entry.server or "Servidor não especificado")
        self._status_label.setText(entry.status.value)
        self._status_dot.set_status(entry.status)
        self._refresh_uptime()

        is_connected = entry.status == VpnStatus.CONNECTED
        self._ip_label.setText(f"IP interno: {entry.local_ip}" if is_connected and entry.local_ip else "")
        self._ip_label.setVisible(bool(is_connected and entry.local_ip))

        if not self._busy:
            is_connecting = entry.status == VpnStatus.CONNECTING
            is_busy = entry.status in (VpnStatus.CONNECTING, VpnStatus.DISCONNECTING)
            self._connect_btn.setEnabled(not is_connected and not is_busy)
            self._disconnect_btn.setEnabled(is_connected and not is_busy)
            self._reconnect_btn.setEnabled(not is_busy)
            # "Cancelar" só faz sentido enquanto uma tentativa de conexão está em
            # andamento (é a única operação demorada e realmente cancelável hoje).
            self._cancel_btn.setVisible(is_connecting)

    def set_busy(self, busy: bool) -> None:
        """Desabilita as ações do cartão enquanto uma operação de configuração está em andamento."""
        self._busy = busy
        for btn in (self._connect_btn, self._disconnect_btn, self._reconnect_btn, self._cancel_btn, self._menu_btn):
            btn.setEnabled(not busy)
        if not busy:
            self.update_entry(self._entry)

    def _refresh_uptime(self) -> None:
        if self._entry.status == VpnStatus.CONNECTED:
            self._uptime_label.setText(format_duration(self._entry.uptime_seconds))
        else:
            self._uptime_label.setText("--:--:--")

    @property
    def vpn_name(self) -> str:
        return self._entry.name
