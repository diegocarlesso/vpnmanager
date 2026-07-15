"""Wrapper de baixo nível para o utilitário rasdial.exe via subprocess."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from utils.constants import DEFAULT_COMMAND_TIMEOUT

logger = logging.getLogger("vpn_manager.rasdial")

# Evita que uma janela de console pisque na tela ao executar o rasdial.
_CREATE_NO_WINDOW = 0x08000000


def _console_output_encoding() -> str:
    """Codepage OEM do console (ex.: cp850), usada pelo rasdial.exe para stdout.

    O rasdial escreve na codepage OEM do console, não na ANSI (locale.getpreferredencoding()).
    Usar a codificação errada corrompe nomes de VPN e mensagens com acentos.
    """
    if os.name != "nt":
        return "utf-8"
    try:
        import ctypes

        return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
    except (AttributeError, OSError, ValueError):
        return "cp850"


_OUTPUT_ENCODING = _console_output_encoding()


@dataclass
class CommandResult:
    """Resultado padronizado de uma execução do rasdial."""

    success: bool
    return_code: int
    stdout: str
    stderr: str
    duration_ms: float


class RasdialManager:
    """Executa comandos rasdial.exe de forma segura, sem bloquear a interface."""

    def __init__(self, timeout: int = DEFAULT_COMMAND_TIMEOUT, executable: Optional[str] = None) -> None:
        self.timeout = timeout
        self.executable = executable or self._resolve_executable()

    @staticmethod
    def _resolve_executable() -> str:
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidate = Path(windir) / "System32" / "rasdial.exe"
        return str(candidate) if candidate.exists() else "rasdial.exe"

    def _run(self, args: List[str]) -> CommandResult:
        start = time.perf_counter()
        try:
            completed = subprocess.run(
                [self.executable, *args],
                capture_output=True,
                timeout=self.timeout,
                creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            duration_ms = (time.perf_counter() - start) * 1000
            stdout = completed.stdout.decode(_OUTPUT_ENCODING, errors="replace").strip()
            stderr = completed.stderr.decode(_OUTPUT_ENCODING, errors="replace").strip()
            return CommandResult(
                success=completed.returncode == 0,
                return_code=completed.returncode,
                stdout=stdout,
                stderr=stderr,
                duration_ms=duration_ms,
            )
        except subprocess.TimeoutExpired:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error("Tempo limite excedido ao executar rasdial (operação: %s)", args[0] if args else "status")
            return CommandResult(False, -1, "", "Tempo limite excedido", duration_ms)
        except OSError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error("Falha ao executar rasdial: %s", exc)
            return CommandResult(False, -1, "", str(exc), duration_ms)

    def connect(self, name: str, username: Optional[str] = None, password: Optional[str] = None) -> CommandResult:
        """Conecta a uma VPN pelo nome. Credenciais, quando fornecidas, nunca são persistidas."""
        args = [name]
        if username is not None and password is not None:
            args.extend([username, password])
        return self._run(args)

    def disconnect(self, name: str) -> CommandResult:
        return self._run([name, "/disconnect"])

    def list_active_connections(self) -> CommandResult:
        return self._run([])

    @staticmethod
    def parse_active_connections(result: CommandResult) -> Set[str]:
        """Extrai os nomes das conexões ativas a partir da saída do rasdial (sem argumentos).

        O formato de saída do rasdial é localizado (ex.: "Connected to" / "Conectado a" e
        "Command completed successfully." / "Comando concluído com êxito."), portanto não é
        seguro filtrar por palavras-chave em um idioma fixo. Em vez disso, usamos a estrutura
        posicional, que é estável independente do idioma do Windows:
            <cabeçalho>
            <nome da conexão 1>
            [<nome da conexão 2>...]
            <rodapé>
        Com 0 ou 1 conexões ativas, a saída tem no máximo 2 linhas (cabeçalho/mensagem de
        "nenhuma conexão" e rodapé), então nenhum nome sobra no meio — comportamento correto.
        """
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if len(lines) < 3:
            return set()
        return set(lines[1:-1])
