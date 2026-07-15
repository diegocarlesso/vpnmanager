"""Executa os scripts PowerShell empacotados em scripts/*.ps1, com entrada/saída em JSON.

Os parâmetros nunca são interpolados em texto de comando (evita injeção); em vez
disso são serializados em um arquivo JSON temporário que cada script lê via
ConvertFrom-Json, e o resultado é lido de outro arquivo JSON temporário escrito
pelo script. Isso também contorna o problema de locale que afeta o rasdial (aqui
não há mensagens traduzidas para interpretar, apenas dados estruturados).
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from core.rasdial_manager import _CREATE_NO_WINDOW
from utils.constants import DEFAULT_PS_TIMEOUT, ELEVATED_PS_TIMEOUT, POWERSHELL_EXE, SCRIPTS_DIR
from utils.helpers import sanitize_for_log

logger = logging.getLogger("vpn_manager.powershell")

_UAC_CANCELLED_CODE = 1223


@dataclass
class PsResult:
    """Resultado padronizado da execução de um script PowerShell empacotado."""

    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration_ms: float = 0.0
    partial: bool = False
    cancelled_by_user: bool = False


class PowerShellRunner:
    """Executa scripts de scripts/*.ps1, solicitando UAC apenas quando necessário."""

    def __init__(self, executable: Optional[str] = None) -> None:
        self.executable = executable or (str(POWERSHELL_EXE) if POWERSHELL_EXE.exists() else "powershell.exe")

    @staticmethod
    def is_admin() -> bool:
        """Indica se o processo atual já está rodando elevado (sem precisar de UAC)."""
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    def run(
        self,
        script_name: str,
        params: Dict[str, Any],
        elevated: bool = False,
        timeout: Optional[int] = None,
    ) -> PsResult:
        """Executa um script síncronamente. Deve ser chamado fora da thread da UI."""
        start = time.perf_counter()
        script_path = SCRIPTS_DIR / script_name
        needs_elevation = elevated and not self.is_admin()
        effective_timeout = timeout or (ELEVATED_PS_TIMEOUT if needs_elevation else DEFAULT_PS_TIMEOUT)

        tmp_dir = Path(tempfile.gettempdir())
        input_fd, input_path = tempfile.mkstemp(suffix=".json", prefix="vpnmgr_in_", dir=tmp_dir)
        output_fd, output_path = tempfile.mkstemp(suffix=".json", prefix="vpnmgr_out_", dir=tmp_dir)
        os.close(output_fd)
        try:
            with os.fdopen(input_fd, "w", encoding="utf-8") as fh:
                json.dump(params, fh)

            if needs_elevation:
                argv = [
                    self.executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(SCRIPTS_DIR / "_elevate.ps1"),
                    str(script_path), input_path, output_path,
                ]
            else:
                argv = [
                    self.executable, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-File", str(script_path), input_path, output_path,
                ]

            try:
                completed = subprocess.run(
                    argv,
                    capture_output=True,
                    timeout=effective_timeout,
                    creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.error("Tempo limite excedido ao executar script PowerShell '%s'", script_name)
                return PsResult(False, {}, "Tempo limite excedido.", duration_ms)
            except OSError as exc:
                duration_ms = (time.perf_counter() - start) * 1000
                logger.error("Falha ao executar PowerShell: %s", exc)
                return PsResult(False, {}, str(exc), duration_ms)

            duration_ms = (time.perf_counter() - start) * 1000

            if needs_elevation and completed.returncode == _UAC_CANCELLED_CODE:
                return PsResult(False, {}, "Operação cancelada pelo usuário.", duration_ms, cancelled_by_user=True)

            return self._read_result(output_path, completed, duration_ms, script_name)
        finally:
            for path in (input_path, output_path):
                try:
                    os.unlink(path)
                except OSError:
                    pass

    @staticmethod
    def _read_result(
        output_path: str,
        completed: "subprocess.CompletedProcess[bytes]",
        duration_ms: float,
        script_name: str,
    ) -> PsResult:
        try:
            # O Windows PowerShell 5.1 grava um BOM UTF-8 com "Out-File -Encoding utf8";
            # utf-8-sig o descarta automaticamente (e também lê UTF-8 sem BOM normalmente).
            with open(output_path, "r", encoding="utf-8-sig") as fh:
                raw = fh.read().strip()
            if not raw:
                raise ValueError("arquivo de saída vazio")
            payload = json.loads(raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            stderr = (
                sanitize_for_log(completed.stderr.decode("utf-8", errors="replace").strip())
                if completed.stderr
                else ""
            )
            logger.error(
                "Saída inválida do script '%s' (código=%s): %s | stderr=%s",
                script_name,
                completed.returncode,
                exc,
                stderr,
            )
            message = stderr or f"Falha ao executar '{script_name}' (código {completed.returncode})."
            return PsResult(False, {}, message, duration_ms)

        return PsResult(
            success=bool(payload.get("success", False)),
            data=payload.get("data") or {},
            error=payload.get("error") or "",
            duration_ms=duration_ms,
            partial=bool(payload.get("partial", False)),
        )
