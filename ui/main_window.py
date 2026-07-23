"""Janela principal da aplicação VPN Manager."""
from __future__ import annotations

import logging
import time
from typing import Dict, Optional, Set

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QStatusBar,
    QSystemTrayIcon,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from core import credential_store
from core.models import VpnEntry, VpnStatus
from core.pbk_parser import PbkParser
from core.powershell_runner import PowerShellRunner
from core.ras_errors import CREDENTIAL_ERROR_CODE, extract_ras_error_code
from core.rasdial_manager import RasdialManager
from core.settings import AppSettings, SettingsManager
from core.vpn_config_manager import VpnConfigManager
from core.vpn_monitor import VpnMonitor
from services.connection_service import CANCELLED_MESSAGE, ConnectionService
from services.notification_service import NotificationService
from services.vpn_config_service import VpnConfigService
from ui.credentials_dialog import CredentialsDialog
from ui.log_window import LogWindow
from ui.settings_dialog import SettingsDialog
from ui.vpn_edit_dialog import VpnEditDialog
from ui.vpn_widget import VpnWidget
from utils.constants import APP_NAME, APP_VERSION
from utils.helpers import load_app_icon
from utils.theme import apply_theme

logger = logging.getLogger("vpn_manager.ui")

_CREDENTIAL_ERROR_HINTS = ("credencial", "senha", "usu", "691", "628", "autentic")

# Janela máxima em que uma queda de conexão detectada pelo monitor ainda é
# atribuída a uma desconexão pedida pelo usuário. Passado esse tempo, a marcação
# expira sozinha (em vez de ficar presa para sempre) e uma queda futura da mesma
# VPN volta a ser tratada como inesperada pelo auto-reconnect.
_USER_DISCONNECT_TTL_SECONDS = 45.0

# Backoff de reconexão automática: tempo de espera (segundos) antes de cada nova
# tentativa após uma falha. A última tentativa repete o último valor da lista.
_AUTO_RECONNECT_BACKOFF_SECONDS = (5.0, 15.0, 30.0, 60.0)
# Após esse número de tentativas malsucedidas, a reconexão automática desiste e
# avisa o usuário em vez de tentar indefinidamente.
_AUTO_RECONNECT_MAX_ATTEMPTS = 5


class MainWindow(QMainWindow):
    """Janela principal: lista de VPNs, barra de ferramentas e bandeja do sistema."""

    # Sinais usados para se comunicar com o VpnMonitor, que vive em outra QThread.
    _request_poll = Signal()
    _request_stop_monitor = Signal()
    _request_interval_change = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(load_app_icon())
        self.resize(860, 580)

        self._settings_manager = SettingsManager()
        settings = self._settings_manager.settings
        apply_theme(settings.theme)

        self._pbk_parser = PbkParser(settings.pbk_directory)
        self._rasdial_manager = RasdialManager(timeout=settings.command_timeout)
        self._connection_service = ConnectionService(self._rasdial_manager)

        self._powershell_runner = PowerShellRunner()
        self._vpn_config_manager = VpnConfigManager(self._powershell_runner, self._rasdial_manager, self._pbk_parser)
        self._vpn_config_service = VpnConfigService(self._vpn_config_manager)

        self._vpn_widgets: Dict[str, VpnWidget] = {}
        self._entries: Dict[str, VpnEntry] = {}
        self._pending_detail_fetches: Set[str] = set()
        self._log_window: Optional[LogWindow] = None

        # Credenciais informadas manualmente com "salvar" marcado: persistidas
        # somente após a operação de conexão ser bem-sucedida.
        self._pending_remember: Dict[str, tuple] = {}
        # VPNs com um connect/reconnect em andamento: evita que um clique duplicado
        # (ex.: usuário reclica "Conectar" enquanto o diálogo de credenciais da
        # tentativa anterior ainda está aberto) dispare uma segunda tentativa sem
        # credenciais que, ao falhar, descartaria a marcação de "lembrar" pendente.
        self._connect_ops_in_flight: Set[str] = set()
        # VPNs cuja desconexão foi pedida explicitamente pelo usuário: usado
        # para não disparar reconexão automática nesses casos. Mapeia
        # key -> prazo (time.monotonic()) até quando a marcação é válida, para
        # não ficar presa para sempre se o disconnect falhar, a VPN já estiver
        # desconectada, ou o monitor perder a transição.
        self._user_disconnecting: Dict[str, float] = {}
        # VPNs com uma tentativa de reconexão automática em andamento: evita
        # disparar novas tentativas a cada ciclo de monitoramento (a cada poll).
        self._auto_reconnecting: Set[str] = set()
        # Número da tentativa atual de reconexão automática por VPN (1-based);
        # resetado quando a conexão é restabelecida ou quando o usuário intervém.
        self._auto_reconnect_attempts: Dict[str, int] = {}
        # Timer de backoff pendente entre tentativas de reconexão automática,
        # para poder cancelá-lo se o usuário intervier manualmente antes de disparar.
        self._auto_reconnect_timers: Dict[str, QTimer] = {}
        # VPNs com uma operação de configuração (editar/excluir) em andamento:
        # essas operações podem desconectar a VPN como efeito colateral (ex.:
        # Set-VpnConnection exige desconectar antes de aplicar mudanças); sem essa
        # marcação, a queda seria confundida com uma falha inesperada e dispararia
        # uma reconexão automática concorrente com a própria edição/exclusão.
        self._config_ops_in_flight: Set[str] = set()

        self._build_ui()
        self._build_tray_icon()
        self._notification_service = NotificationService(self._tray_icon)

        self._connection_service.operation_finished.connect(self._on_operation_finished)
        self._vpn_config_service.operation_finished.connect(self._on_config_operation_finished)
        self._vpn_config_service.details_fetched.connect(self._on_details_fetched)

        self._start_monitor(settings.refresh_interval)

    @property
    def settings(self) -> AppSettings:
        return self._settings_manager.settings

    @property
    def tray_icon_available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    # ------------------------------------------------------------------
    # Construção de UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        toolbar = QToolBar("Principal", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        refresh_action = QAction("Atualizar", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._force_refresh)
        toolbar.addAction(refresh_action)

        self._add_vpn_action = QAction("Adicionar VPN", self)
        self._add_vpn_action.triggered.connect(self._open_add_vpn_dialog)
        self._update_add_vpn_action_state()
        toolbar.addAction(self._add_vpn_action)

        settings_action = QAction("Configurações", self)
        settings_action.triggered.connect(self._open_settings)
        toolbar.addAction(settings_action)

        logs_action = QAction("Logs", self)
        logs_action.triggered.connect(self._open_log_window)
        toolbar.addAction(logs_action)

        toolbar.addSeparator()

        self._search_edit = QLineEdit(self)
        self._search_edit.setPlaceholderText("Buscar VPN…")
        self._search_edit.setMaximumWidth(240)
        self._search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self._search_edit)

        central = QWidget(self)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self._list_container = QWidget(self)
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._list_layout.setSpacing(6)
        self._list_layout.setContentsMargins(8, 8, 8, 8)

        self._empty_label = QLabel("Nenhuma conexão VPN encontrada.", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet("color: #888; padding: 32px;")
        self._list_layout.addWidget(self._empty_label)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._list_container)
        root_layout.addWidget(scroll)

        self.setCentralWidget(central)

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        self._active_label = QLabel("0 conexão(ões) ativa(s)", self)
        status_bar.addPermanentWidget(self._active_label)

    def _build_tray_icon(self) -> None:
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip(APP_NAME)

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Abrir")
        show_action.triggered.connect(self.bring_to_foreground)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("Sair")
        quit_action.triggered.connect(self._quit_application)

        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.show()

    # ------------------------------------------------------------------
    # Monitoramento em background
    # ------------------------------------------------------------------
    def _start_monitor(self, interval_seconds: int) -> None:
        self._monitor_thread = QThread(self)
        self._monitor = VpnMonitor(
            self._pbk_parser, self._rasdial_manager, interval_seconds, vpn_config_manager=self._vpn_config_manager
        )
        self._monitor.moveToThread(self._monitor_thread)

        self._monitor_thread.started.connect(self._monitor.start)
        self._monitor.vpns_updated.connect(self._on_vpns_updated)
        self._monitor.error_occurred.connect(self._on_monitor_error)

        # Conexões explicitamente enfileiradas: cruzam a fronteira de thread com segurança.
        self._request_poll.connect(self._monitor.poll_once, Qt.ConnectionType.QueuedConnection)
        self._request_stop_monitor.connect(self._monitor.stop, Qt.ConnectionType.QueuedConnection)
        self._request_interval_change.connect(self._monitor.set_interval, Qt.ConnectionType.QueuedConnection)

        self._monitor_thread.start()

    def _force_refresh(self) -> None:
        self._request_poll.emit()

    # ------------------------------------------------------------------
    # Atualização da lista de VPNs
    # ------------------------------------------------------------------
    def _on_vpns_updated(self, entries: Dict[str, VpnEntry]) -> None:
        favorite = self._settings_manager.settings.favorite_vpn
        for entry in entries.values():
            entry.is_favorite = favorite is not None and entry.name.casefold() == favorite.casefold()
            entry.has_saved_credentials = credential_store.has_saved_credentials(entry.name)

        if self._settings_manager.settings.auto_reconnect:
            self._check_auto_reconnect(entries)

        previous_keys = set(self._entries.keys())
        new_keys = set(entries.keys())

        for key in previous_keys - new_keys:
            widget = self._vpn_widgets.pop(key, None)
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        for key, entry in entries.items():
            widget = self._vpn_widgets.get(key)
            if widget is None:
                widget = VpnWidget(entry, self._can_edit_vpns(), self._list_container)
                widget.connect_requested.connect(self._on_connect_requested)
                widget.disconnect_requested.connect(self._on_disconnect_requested)
                widget.reconnect_requested.connect(self._on_reconnect_requested)
                widget.cancel_requested.connect(self._on_cancel_requested)
                widget.favorite_toggled.connect(self._on_favorite_toggled)
                widget.edit_requested.connect(self._on_edit_requested)
                widget.delete_requested.connect(self._on_delete_requested)
                widget.forget_credentials_requested.connect(self._on_forget_credentials_requested)
                self._vpn_widgets[key] = widget
                self._list_layout.addWidget(widget)
            widget.update_entry(entry)

        self._entries = entries
        self._empty_label.setVisible(len(entries) == 0)
        self._reorder_widgets(entries)
        self._apply_filter(self._search_edit.text())

        active_count = sum(1 for e in entries.values() if e.status == VpnStatus.CONNECTED)
        self._active_label.setText(f"{active_count} conexão(ões) ativa(s)")

    def _check_auto_reconnect(self, new_entries: Dict[str, VpnEntry]) -> None:
        """Detecta VPNs que estavam conectadas e caíram sem pedido do usuário, e reconecta."""
        for key, previous in self._entries.items():
            if previous.status != VpnStatus.CONNECTED:
                continue
            new_entry = new_entries.get(key)
            if new_entry is None or new_entry.status != VpnStatus.DISCONNECTED:
                continue
            deadline = self._user_disconnecting.pop(key, None)
            if deadline is not None and time.monotonic() <= deadline:
                # Consome a marcação: essa queda específica foi pedida pelo usuário.
                continue
            if key in self._auto_reconnecting:
                continue
            if key in self._config_ops_in_flight:
                # Queda causada por uma edição/exclusão em andamento (não uma
                # queda real da VPN); reconectar agora colidiria com a operação.
                continue
            self._start_auto_reconnect(new_entry)

    def _start_auto_reconnect(self, entry: VpnEntry) -> None:
        """Primeira tentativa de reconexão automática após uma queda detectada."""
        key = entry.key()
        self._auto_reconnect_attempts[key] = 1
        logger.info("Conexão '%s' caiu inesperadamente; tentando reconectar automaticamente.", entry.name)
        self._issue_auto_reconnect(key, entry)

    def _issue_auto_reconnect(self, key: str, entry: VpnEntry) -> None:
        """Dispara uma tentativa de conexão (primeira ou de um backoff) e marca o estado."""
        self._auto_reconnecting.add(key)
        self._connect_ops_in_flight.add(key)
        attempt = self._auto_reconnect_attempts.get(key, 1)
        self._notification_service.notify(
            entry.name,
            f"Conexão perdida — tentando reconectar automaticamente… ({attempt}/{_AUTO_RECONNECT_MAX_ATTEMPTS})",
            QSystemTrayIcon.MessageIcon.Warning,
        )
        username, password = credential_store.load_credentials(entry.name, entry.phonebook_path)
        self._set_transient_status(key, VpnStatus.CONNECTING)
        self._connection_service.connect(
            key, entry.name, username=username, password=password, phonebook_path=entry.phonebook_path
        )

    def _schedule_auto_reconnect_retry(self, key: str, name: str) -> None:
        """Agenda a próxima tentativa de reconexão automática com backoff, ou desiste."""
        attempt = self._auto_reconnect_attempts.get(key, 1)
        if attempt >= _AUTO_RECONNECT_MAX_ATTEMPTS:
            logger.warning("Reconexão automática de '%s' desistiu após %d tentativa(s).", name, attempt)
            self._notification_service.notify(
                name,
                f"Não foi possível reconectar automaticamente após {attempt} tentativas. Conecte manualmente.",
                QSystemTrayIcon.MessageIcon.Critical,
            )
            self._auto_reconnect_attempts.pop(key, None)
            return

        delay_index = min(attempt - 1, len(_AUTO_RECONNECT_BACKOFF_SECONDS) - 1)
        delay_seconds = _AUTO_RECONNECT_BACKOFF_SECONDS[delay_index]
        self._auto_reconnect_attempts[key] = attempt + 1
        logger.info(
            "Reconexão automática de '%s' falhou (tentativa %d); nova tentativa em %.0fs.",
            name, attempt, delay_seconds,
        )

        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._retry_auto_reconnect(key))
        self._auto_reconnect_timers[key] = timer
        timer.start(int(delay_seconds * 1000))

    def _retry_auto_reconnect(self, key: str) -> None:
        self._auto_reconnect_timers.pop(key, None)
        if key in self._config_ops_in_flight:
            # Uma edição/exclusão começou enquanto o backoff esperava; não interferir.
            self._auto_reconnect_attempts.pop(key, None)
            return
        if not self._settings_manager.settings.auto_reconnect:
            # Usuário desligou a reconexão automática enquanto o backoff esperava.
            self._auto_reconnect_attempts.pop(key, None)
            return
        entry = self._entries.get(key)
        if entry is None or entry.status == VpnStatus.CONNECTED:
            # VPN sumiu da lista ou já foi reconectada por outro caminho (ex.: manual).
            self._auto_reconnect_attempts.pop(key, None)
            return
        self._issue_auto_reconnect(key, entry)

    def _cancel_pending_auto_reconnect(self, key: str) -> None:
        """Cancela um backoff de reconexão automática pendente para `key`, se houver.

        Chamado sempre que o usuário intervém manualmente (conectar/desconectar/
        reconectar/editar/excluir), para que a tentativa automática agendada não
        dispare por cima de uma ação explícita do usuário.
        """
        timer = self._auto_reconnect_timers.pop(key, None)
        if timer is not None:
            timer.stop()
        self._auto_reconnect_attempts.pop(key, None)

    def _reorder_widgets(self, entries: Dict[str, VpnEntry]) -> None:
        """Reordena os cartões: conectadas no topo, demais em ordem alfabética."""
        ordered_keys = sorted(
            entries.keys(),
            key=lambda k: (entries[k].status != VpnStatus.CONNECTED, entries[k].name.casefold()),
        )
        for key in ordered_keys:
            widget = self._vpn_widgets[key]
            self._list_layout.removeWidget(widget)
            self._list_layout.addWidget(widget)

    def _on_monitor_error(self, message: str) -> None:
        logger.error("Erro no monitor: %s", message)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        for key, widget in self._vpn_widgets.items():
            if not needle:
                widget.setVisible(True)
                continue
            entry = self._entries.get(key)
            visible = entry is not None and (
                needle in entry.name.casefold() or needle in (entry.server or "").casefold()
            )
            widget.setVisible(visible)

    # ------------------------------------------------------------------
    # Ações de conexão
    # ------------------------------------------------------------------
    def _on_connect_requested(self, key: str) -> None:
        if key in self._connect_ops_in_flight:
            return  # Já há uma tentativa de conexão em andamento para esta VPN.
        entry = self._entries.get(key)
        if entry is None:
            return
        self._cancel_pending_auto_reconnect(key)
        self._connect_ops_in_flight.add(key)
        self._user_disconnecting.pop(key, None)
        username, password = credential_store.load_credentials(entry.name, entry.phonebook_path)
        logger.info(
            "Conectar '%s' (%s): credenciais salvas encontradas=%s", entry.name, entry.scope, username is not None
        )
        self._set_transient_status(key, VpnStatus.CONNECTING)
        self._connection_service.connect(
            key, entry.name, username=username, password=password, phonebook_path=entry.phonebook_path
        )

    def _on_disconnect_requested(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        self._cancel_pending_auto_reconnect(key)
        self._user_disconnecting[key] = time.monotonic() + _USER_DISCONNECT_TTL_SECONDS
        self._set_transient_status(key, VpnStatus.DISCONNECTING)
        self._connection_service.disconnect(key, entry.name)

    def _on_reconnect_requested(self, key: str) -> None:
        if key in self._connect_ops_in_flight:
            return  # Já há uma tentativa de conexão em andamento para esta VPN.
        entry = self._entries.get(key)
        if entry is None:
            return
        self._cancel_pending_auto_reconnect(key)
        self._connect_ops_in_flight.add(key)
        self._user_disconnecting.pop(key, None)
        username, password = credential_store.load_credentials(entry.name, entry.phonebook_path)
        logger.info(
            "Reconectar '%s' (%s): credenciais salvas encontradas=%s", entry.name, entry.scope, username is not None
        )
        self._set_transient_status(key, VpnStatus.CONNECTING)
        self._connection_service.reconnect(
            key, entry.name, username=username, password=password, phonebook_path=entry.phonebook_path
        )

    def _on_cancel_requested(self, key: str) -> None:
        """Cancela uma tentativa de conexão em andamento (botão "Cancelar" durante Conectando)."""
        entry = self._entries.get(key)
        name = entry.name if entry is not None else key
        logger.info("Cancelamento de conexão solicitado pelo usuário para '%s'.", name)
        self._connection_service.cancel(key)

    def _on_favorite_toggled(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        current = self._settings_manager.settings.favorite_vpn
        new_value = None if current and current.casefold() == entry.name.casefold() else entry.name
        self._settings_manager.update(favorite_vpn=new_value)
        self._force_refresh()

    def _set_transient_status(self, key: str, status: VpnStatus) -> None:
        """Reflete imediatamente na UI um estado transitório (Conectando/Desconectando)."""
        widget = self._vpn_widgets.get(key)
        entry = self._entries.get(key)
        if widget is not None and entry is not None:
            entry.status = status
            widget.update_entry(entry)

    def _on_operation_finished(
        self, key: str, name: str, operation: str, success: bool, message: str, duration_ms: float
    ) -> None:
        was_auto_reconnect = key in self._auto_reconnecting
        self._auto_reconnecting.discard(key)
        if operation in ("connect", "reconnect"):
            self._connect_ops_in_flight.discard(key)
        if operation == "disconnect" and not success:
            # Disconnect falhou (ex.: já estava desconectada, erro de rasdial): nenhuma
            # transição real vai ocorrer para consumir a marcação, então ela ficaria
            # presa até o TTL expirar por conta própria. Como não há nada a suprimir
            # aqui, limpa imediatamente.
            self._user_disconnecting.pop(key, None)

        icon = QSystemTrayIcon.MessageIcon.Information if success else QSystemTrayIcon.MessageIcon.Warning
        self._notification_service.notify(name, message, icon)

        if success and operation in ("connect", "reconnect"):
            self._auto_reconnect_attempts.pop(key, None)
            # Só remove a marcação de "lembrar" quando ela é de fato usada: uma
            # tentativa concorrente sem credenciais (ex.: clique duplicado em
            # "Conectar" enquanto o diálogo desta VPN ainda está aberto) não pode
            # descartar silenciosamente o pedido de salvar da tentativa correta.
            pending = self._pending_remember.pop(key, None)
            if pending is not None:
                username, password = pending
                if credential_store.save_credentials(name, username, password):
                    logger.info("Credenciais salvas com segurança para '%s'.", name)
                else:
                    logger.warning("Falha ao salvar credenciais para '%s'.", name)

        if not success and operation in ("connect", "reconnect"):
            if message == CANCELLED_MESSAGE:
                # Cancelamento explícito do usuário: não insiste com backoff nem
                # reabre o diálogo de credenciais.
                self._auto_reconnect_attempts.pop(key, None)
            else:
                credential_error = self._looks_like_credential_error(message)
                if credential_error and credential_store.has_saved_credentials(name):
                    # Credenciais salvas podem estar desatualizadas (ex.: senha trocada);
                    # descarta-as para não insistir num valor que sabemos estar errado.
                    credential_store.delete_credentials(name)
                if was_auto_reconnect and not credential_error:
                    # Falha "genuína" (rede, servidor, etc.) numa tentativa automática:
                    # tenta de novo com backoff em vez de desistir silenciosamente.
                    self._schedule_auto_reconnect_retry(key, name)
                elif credential_error:
                    self._prompt_and_retry_with_credentials(key, name)
        self._force_refresh()

    @staticmethod
    def _looks_like_credential_error(message: str) -> bool:
        # Código RAS 691 é o sinal mais confiável (estável entre idiomas do Windows);
        # os hints textuais continuam como fallback para mensagens sem código
        # reconhecível (ex.: mensagens antigas já sanitizadas ou traduções não mapeadas).
        if extract_ras_error_code(message) == CREDENTIAL_ERROR_CODE:
            return True
        lowered = message.lower()
        return any(hint in lowered for hint in _CREDENTIAL_ERROR_HINTS)

    def _prompt_and_retry_with_credentials(self, key: str, name: str) -> None:
        # Mantém o guard de conexão em andamento durante o diálogo (modal, mas que
        # processa a fila de eventos): sem isso, um refresh assíncrono pode reabilitar
        # o botão "Conectar" enquanto o diálogo ainda está aberto, permitindo um
        # clique duplicado que dispara uma tentativa concorrente sem credenciais.
        self._connect_ops_in_flight.add(key)
        # Se a janela estiver minimizada/na bandeja, um diálogo modal filho pode
        # ficar aberto sem que o usuário perceba — e como o guard acima trava
        # cliques em "Conectar" até o diálogo ser respondido, isso parece
        # exatamente com "clico em Conectar e nada acontece".
        if not self.isVisible() or self.isMinimized():
            self.bring_to_foreground()
        dialog = CredentialsDialog(name, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self._connect_ops_in_flight.discard(key)
            return
        username, password, remember = dialog.result_credentials()
        logger.info("Diálogo de credenciais de '%s' aceito: salvar_marcado=%s", name, remember)
        if remember:
            self._pending_remember[key] = (username, password)
        entry = self._entries.get(key)
        phonebook_path = entry.phonebook_path if entry is not None else None
        self._set_transient_status(key, VpnStatus.CONNECTING)
        self._connection_service.connect(
            key, name, username=username, password=password, phonebook_path=phonebook_path
        )

    # ------------------------------------------------------------------
    # Adicionar / editar / excluir VPN
    # ------------------------------------------------------------------
    def _can_edit_vpns(self) -> bool:
        """Adicionar/editar/excluir exige os phonebooks reais do Windows.

        Um diretório PBK personalizado (Configurações) não corresponde a nenhum
        escopo que os cmdlets Add/Set/Remove-VpnConnection entendam.
        """
        return not self._settings_manager.settings.pbk_directory

    def _update_add_vpn_action_state(self) -> None:
        can_edit = self._can_edit_vpns()
        self._add_vpn_action.setEnabled(can_edit)
        self._add_vpn_action.setToolTip(
            "" if can_edit else "Indisponível com diretório PBK personalizado nas configurações."
        )

    def _open_add_vpn_dialog(self) -> None:
        dialog = VpnEditDialog(details=None, is_admin=self._vpn_config_manager.is_admin(), parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result()
            self._vpn_config_service.add(**result)
            username, password = dialog.result_credentials()
            if username:
                credential_store.save_credentials(result["name"], username, password)

    def _on_edit_requested(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None or key in self._pending_detail_fetches:
            return
        self._cancel_pending_auto_reconnect(key)
        self._pending_detail_fetches.add(key)
        widget = self._vpn_widgets.get(key)
        if widget is not None:
            widget.set_busy(True)
        self._vpn_config_service.fetch_details(entry.name, entry.scope == "system")

    def _on_details_fetched(self, name: str, all_users: bool, details: object) -> None:
        # fetch_details() é sempre chamado a partir de um entry.scope conhecido
        # (ver _on_edit_requested), então all_users reconstrói a mesma chave escopo+nome
        # sem ambiguidade, mesmo que exista outra VPN com o mesmo nome no outro escopo.
        key = f"{'system' if all_users else 'user'}:{name.casefold()}"
        self._pending_detail_fetches.discard(key)
        widget = self._vpn_widgets.get(key)
        if widget is not None:
            widget.set_busy(False)
        if key not in self._entries:
            return  # VPN removida/alterada enquanto os detalhes eram buscados
        if details is None:
            QMessageBox.warning(self, "Editar VPN", f"Não foi possível obter a configuração de '{name}'.")
            return
        entry = self._entries[key]
        saved_username, saved_password = credential_store.load_credentials(name, entry.phonebook_path)
        dialog = VpnEditDialog(
            details=details,
            is_admin=self._vpn_config_manager.is_admin(),
            parent=self,
            username=saved_username or "",
            password=saved_password or "",
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._config_ops_in_flight.add(key)
            self._vpn_config_service.update(**dialog.result())
            username, password = dialog.result_credentials()
            if username:
                credential_store.save_credentials(name, username, password)

    def _on_delete_requested(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        self._cancel_pending_auto_reconnect(key)
        self._config_ops_in_flight.add(key)
        widget = self._vpn_widgets.get(key)
        if widget is not None:
            widget.set_busy(True)
        self._vpn_config_service.delete(entry.name, entry.scope == "system")

    def _on_forget_credentials_requested(self, key: str) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        answer = QMessageBox.question(
            self, "Esquecer credenciais", f"Remover as credenciais salvas de '{entry.name}' deste computador?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        credential_store.delete_credentials(entry.name)
        self._force_refresh()

    def _on_config_operation_finished(
        self, name: str, operation: str, success: bool, message: str, partial: bool, all_users: bool
    ) -> None:
        key = f"{'system' if all_users else 'user'}:{name.casefold()}"
        self._config_ops_in_flight.discard(key)
        widget = self._vpn_widgets.get(key)
        if widget is not None:
            widget.set_busy(False)
        icon = (
            QSystemTrayIcon.MessageIcon.Information
            if success and not partial
            else QSystemTrayIcon.MessageIcon.Warning
        )
        self._notification_service.notify(name, message, icon)
        if success:
            if operation == "delete":
                credential_store.delete_credentials(name)
            self._force_refresh()

    # ------------------------------------------------------------------
    # Configurações e logs
    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._settings_manager.settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_settings = dialog.result_settings()
            self._settings_manager.update(**new_settings.__dict__)
            self._settings_manager.apply_startup_registration()
            apply_theme(new_settings.theme)
            self._pbk_parser.set_custom_directory(new_settings.pbk_directory)
            self._rasdial_manager.timeout = new_settings.command_timeout
            self._request_interval_change.emit(new_settings.refresh_interval)
            self._update_add_vpn_action_state()
            for widget in self._vpn_widgets.values():
                widget.setParent(None)
                widget.deleteLater()
            self._vpn_widgets.clear()
            self._entries.clear()
            self._force_refresh()

    def _open_log_window(self) -> None:
        if self._log_window is None:
            self._log_window = LogWindow(self)
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()

    # ------------------------------------------------------------------
    # Bandeja do sistema e encerramento
    # ------------------------------------------------------------------
    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.bring_to_foreground()

    def bring_to_foreground(self) -> None:
        """Restaura e ativa a janela: usado pela bandeja e por uma segunda instância do .exe."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_application(self) -> None:
        self._shutdown_monitor()
        QApplication.instance().quit()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - assinatura definida pelo Qt
        if self._settings_manager.settings.minimize_to_tray and QSystemTrayIcon.isSystemTrayAvailable():
            event.ignore()
            self.hide()
            self._notification_service.notify(
                APP_NAME, "A aplicação continua em execução na bandeja do sistema."
            )
        else:
            self._shutdown_monitor()
            event.accept()

    def _shutdown_monitor(self) -> None:
        if hasattr(self, "_monitor_thread") and self._monitor_thread.isRunning():
            self._request_stop_monitor.emit()
            self._monitor_thread.quit()
            self._monitor_thread.wait(3000)
