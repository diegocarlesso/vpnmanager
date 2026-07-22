"""Armazenamento seguro de credenciais de VPN no Windows Credential Manager.

Usa a API nativa do Windows (advapi32) via ctypes em vez de uma dependência
externa (pywin32) só para isto. As credenciais ficam protegidas pelo DPAPI do
próprio Windows, atreladas ao usuário logado — a aplicação nunca grava
usuário/senha em texto claro em disco.
"""
from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Optional, Tuple

logger = logging.getLogger("vpn_manager.credentials")

_TARGET_PREFIX = "VPNManager:VPN:"

_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2


class _CREDENTIAL(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_char)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _load_advapi32():
    if not hasattr(ctypes, "windll"):
        return None
    try:
        advapi32 = ctypes.windll.advapi32
        advapi32.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIAL)),
        ]
        advapi32.CredReadW.restype = wintypes.BOOL
        advapi32.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIAL), wintypes.DWORD]
        advapi32.CredWriteW.restype = wintypes.BOOL
        advapi32.CredFree.argtypes = [ctypes.c_void_p]
        advapi32.CredFree.restype = None
        advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        advapi32.CredDeleteW.restype = wintypes.BOOL
        return advapi32
    except (AttributeError, OSError):
        return None


_advapi32 = _load_advapi32()


def _target_name(vpn_name: str) -> str:
    return f"{_TARGET_PREFIX}{vpn_name.casefold()}"


def load_credentials(vpn_name: str) -> Tuple[Optional[str], Optional[str]]:
    """Lê usuário/senha salvos para a VPN informada, se existirem."""
    if _advapi32 is None:
        return None, None
    cred_ptr = ctypes.POINTER(_CREDENTIAL)()
    ok = _advapi32.CredReadW(_target_name(vpn_name), _CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr))
    if not ok:
        return None, None
    try:
        cred = cred_ptr.contents
        username = cred.UserName or None
        if cred.CredentialBlobSize and cred.CredentialBlob:
            raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
            password = raw.decode("utf-16-le", errors="replace")
        else:
            password = None
        return username, password
    finally:
        _advapi32.CredFree(cred_ptr)


def has_saved_credentials(vpn_name: str) -> bool:
    """Verifica se há credencial salva, sem decodificar a senha em memória Python.

    Chamado a cada ciclo do monitor (a cada 2-10s) para toda VPN listada — usar
    load_credentials() aqui materializaria a senha em texto claro num objeto
    Python a cada poll, sem necessidade. CredReadW ainda decripta o blob
    internamente (isso é inerente à API do Windows), mas evitamos copiá-lo para
    uma string Python quando só precisamos saber se ele existe.
    """
    if _advapi32 is None:
        return False
    cred_ptr = ctypes.POINTER(_CREDENTIAL)()
    ok = _advapi32.CredReadW(_target_name(vpn_name), _CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr))
    if not ok:
        return False
    try:
        cred = cred_ptr.contents
        return bool(cred.UserName) and cred.CredentialBlobSize > 0
    finally:
        _advapi32.CredFree(cred_ptr)


def save_credentials(vpn_name: str, username: str, password: str) -> bool:
    """Salva/sobrescreve usuário e senha da VPN, criptografados pelo Windows."""
    if _advapi32 is None:
        return False
    blob = password.encode("utf-16-le")
    blob_buf = ctypes.create_string_buffer(blob, len(blob))
    credential = _CREDENTIAL(
        Flags=0,
        Type=_CRED_TYPE_GENERIC,
        TargetName=_target_name(vpn_name),
        Comment="Credenciais de VPN salvas pelo VPN Manager",
        CredentialBlobSize=len(blob),
        CredentialBlob=ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_char)),
        Persist=_CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount=0,
        Attributes=None,
        TargetAlias=None,
        UserName=username,
    )
    ok = bool(_advapi32.CredWriteW(ctypes.byref(credential), 0))
    if not ok:
        logger.warning("Falha ao salvar credenciais para '%s' (erro %s)", vpn_name, ctypes.GetLastError())
    return ok


def delete_credentials(vpn_name: str) -> bool:
    if _advapi32 is None:
        return False
    return bool(_advapi32.CredDeleteW(_target_name(vpn_name), _CRED_TYPE_GENERIC, 0))
