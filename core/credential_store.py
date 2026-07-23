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

# --- Credenciais nativas do RAS (RasGetEntryDialParamsW) --------------------
#
# Quando o usuário salva usuário/senha pela tela nativa do Windows
# (Configurações > Rede > VPN > editar > "Salvar minhas informações de
# login"), o RAS NÃO usa o Credential Manager genérico (CredReadW/CredWriteW)
# — ele mantém essas credenciais associadas à entrada do próprio phonebook
# (sinalizado por CacheCredentials=1 no .pbk) através de uma API separada,
# RasGetEntryDialParamsW. Por isso VPNs configuradas fora deste app (ou por
# versões antigas dele) nunca apareciam em has_saved_credentials/
# load_credentials, mesmo com credenciais realmente salvas pelo Windows.
_RAS_MAX_ENTRY_NAME = 256
_RAS_MAX_PHONE_NUMBER = 128
_RAS_MAX_CALLBACK_NUMBER = 128
_UNLEN = 256
_PWLEN = 256
_DNLEN = 15
_ERROR_INVALID_SIZE = 632


def _rasdialparams_fields(with_win2000_fields: bool):
    fields = [
        ("dwSize", wintypes.DWORD),
        ("szEntryName", wintypes.WCHAR * (_RAS_MAX_ENTRY_NAME + 1)),
        ("szPhoneNumber", wintypes.WCHAR * (_RAS_MAX_PHONE_NUMBER + 1)),
        ("szCallbackNumber", wintypes.WCHAR * (_RAS_MAX_CALLBACK_NUMBER + 1)),
        ("szUserName", wintypes.WCHAR * (_UNLEN + 1)),
        ("szPassword", wintypes.WCHAR * (_PWLEN + 1)),
        ("szDomain", wintypes.WCHAR * (_DNLEN + 1)),
    ]
    if with_win2000_fields:
        fields += [("dwSubEntry", wintypes.DWORD), ("dwCallbackId", wintypes.ULONG)]
    return fields


class _RASDIALPARAMSW(ctypes.Structure):
    """Layout documentado (MSDN), com dwSubEntry/dwCallbackId."""

    _fields_ = _rasdialparams_fields(with_win2000_fields=True)


class _RASDIALPARAMSW_LEGACY(ctypes.Structure):
    """Fallback sem os campos finais: algumas versões do rasapi32.dll rejeitam
    o dwSize do layout documentado com ERROR_INVALID_SIZE (632)."""

    _fields_ = _rasdialparams_fields(with_win2000_fields=False)


def _load_rasapi32():
    if not hasattr(ctypes, "windll"):
        return None
    try:
        rasapi32 = ctypes.windll.rasapi32
        rasapi32.RasGetEntryDialParamsW.argtypes = [
            wintypes.LPCWSTR,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
        ]
        rasapi32.RasGetEntryDialParamsW.restype = wintypes.DWORD
        return rasapi32
    except (AttributeError, OSError):
        return None


_rasapi32 = _load_rasapi32()


def _load_native_ras_credentials(vpn_name: str, phonebook_path: str) -> Tuple[Optional[str], Optional[str]]:
    """Lê usuário/senha cacheados nativamente pelo RAS para esta entrada do .pbk."""
    if _rasapi32 is None or not phonebook_path:
        return None, None
    for struct_cls in (_RASDIALPARAMSW, _RASDIALPARAMSW_LEGACY):
        params = struct_cls()
        params.dwSize = ctypes.sizeof(struct_cls)
        params.szEntryName = vpn_name
        has_password = wintypes.BOOL()
        rc = _rasapi32.RasGetEntryDialParamsW(phonebook_path, ctypes.byref(params), ctypes.byref(has_password))
        if rc == _ERROR_INVALID_SIZE:
            continue  # tenta o outro layout de estrutura
        if rc != 0 or not has_password.value or not params.szUserName:
            return None, None
        return params.szUserName, params.szPassword
    return None, None


def _target_name(vpn_name: str) -> str:
    return f"{_TARGET_PREFIX}{vpn_name.casefold()}"


def load_credentials(vpn_name: str, phonebook_path: str = "") -> Tuple[Optional[str], Optional[str]]:
    """Lê usuário/senha salvos para a VPN informada, se existirem.

    Primeiro tenta o que este app salvou (Credential Manager genérico, sob seu
    próprio alvo); só recorre ao cache nativo do RAS se não achar nada ali —
    preserva uma credencial que o usuário tenha explicitamente atualizado
    pelo app, mesmo que o Windows também tenha uma mais antiga guardada.
    """
    username, password = None, None
    if _advapi32 is not None:
        cred_ptr = ctypes.POINTER(_CREDENTIAL)()
        ok = _advapi32.CredReadW(_target_name(vpn_name), _CRED_TYPE_GENERIC, 0, ctypes.byref(cred_ptr))
        if ok:
            try:
                cred = cred_ptr.contents
                username = cred.UserName or None
                if cred.CredentialBlobSize and cred.CredentialBlob:
                    raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
                    password = raw.decode("utf-16-le", errors="replace")
            finally:
                _advapi32.CredFree(cred_ptr)
    if username is not None:
        return username, password
    return _load_native_ras_credentials(vpn_name, phonebook_path)


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
