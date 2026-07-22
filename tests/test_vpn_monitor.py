"""Testes de core.vpn_monitor: o monitor não pode inventar estado quando o rasdial falha."""
from __future__ import annotations

from datetime import datetime

from core.models import VpnEntry, VpnStatus
from core.rasdial_manager import CommandResult
from core.vpn_monitor import VpnMonitor

# QApplication de sessão vem de tests/conftest.py (qt_application, autouse).


class _FakePbkParser:
    def __init__(self, entries):
        self._entries = entries

    def get_all_vpn_entries(self):
        # Uma cópia rasa por chamada, como o parser real faria ao reler o .pbk.
        return {k: VpnEntry(**{**v.__dict__}) for k, v in self._entries.items()}


class _FailingRasdialManager:
    def list_active_connections(self):
        return CommandResult(False, 1, "", "RPC server unavailable", 5.0)

    @staticmethod
    def parse_active_connections(result):
        return set()


class _SucceedingRasdialManager:
    def __init__(self, active_names):
        self._active_names = active_names

    def list_active_connections(self):
        return CommandResult(True, 0, "\n".join(["h", *self._active_names, "f"]), "", 5.0)

    @staticmethod
    def parse_active_connections(result):
        return set(result.stdout.splitlines()[1:-1])


def test_preserves_last_known_status_when_rasdial_query_fails() -> None:
    entries = {
        "user:myvpn": VpnEntry(
            name="MyVPN", scope="user", status=VpnStatus.DISCONNECTED,  # será sobrescrito abaixo
        )
    }
    monitor = VpnMonitor(_FakePbkParser(entries), _FailingRasdialManager(), interval_seconds=5)
    previous_connected = VpnEntry(
        name="MyVPN", scope="user", status=VpnStatus.CONNECTED,
        connected_since=datetime.now(), local_ip="10.0.0.5",
    )
    monitor._known_entries = {"user:myvpn": previous_connected}

    errors = []
    updated = []
    monitor.error_occurred.connect(errors.append)
    monitor.vpns_updated.connect(updated.append)

    monitor.poll_once()  # não deve levantar exceção

    assert errors, "error_occurred deveria ter sido emitido quando a consulta falha"
    assert updated, "vpns_updated deveria ser emitido mesmo em falha (preservando estado)"
    result_entry = updated[0]["user:myvpn"]
    assert result_entry.status == VpnStatus.CONNECTED, "não deveria marcar como desconectado só por falha de consulta"
    assert result_entry.local_ip == "10.0.0.5"


def test_does_not_crash_when_rasdial_fails_and_no_previous_state_exists() -> None:
    entries = {"user:novavpn": VpnEntry(name="NovaVPN", scope="user", status=VpnStatus.DISCONNECTED)}
    monitor = VpnMonitor(_FakePbkParser(entries), _FailingRasdialManager(), interval_seconds=5)
    # _known_entries vazio: VPN nunca vista antes de a consulta começar a falhar.
    updated = []
    monitor.vpns_updated.connect(updated.append)
    monitor.poll_once()
    assert updated[0]["user:novavpn"].status == VpnStatus.DISCONNECTED


def test_normal_poll_marks_active_connections_as_connected() -> None:
    entries = {
        "user:vpn1": VpnEntry(name="VPN1", scope="user", status=VpnStatus.DISCONNECTED),
        "user:vpn2": VpnEntry(name="VPN2", scope="user", status=VpnStatus.DISCONNECTED),
    }
    monitor = VpnMonitor(_FakePbkParser(entries), _SucceedingRasdialManager(["VPN1"]), interval_seconds=5)
    updated = []
    monitor.vpns_updated.connect(updated.append)
    monitor.poll_once()

    result = updated[0]
    assert result["user:vpn1"].status == VpnStatus.CONNECTED
    assert result["user:vpn2"].status == VpnStatus.DISCONNECTED


def test_connected_since_is_preserved_across_polls_while_still_connected() -> None:
    entries = {"user:vpn1": VpnEntry(name="VPN1", scope="user", status=VpnStatus.DISCONNECTED)}
    monitor = VpnMonitor(_FakePbkParser(entries), _SucceedingRasdialManager(["VPN1"]), interval_seconds=5)
    updated = []
    monitor.vpns_updated.connect(updated.append)

    monitor.poll_once()
    first_connected_since = updated[0]["user:vpn1"].connected_since
    assert first_connected_since is not None

    monitor.poll_once()
    second_connected_since = updated[1]["user:vpn1"].connected_since
    assert second_connected_since == first_connected_since
