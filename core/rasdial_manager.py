"""Wrapper de baixo nível para o utilitário rasdial.exe via subprocess."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from utils.constants import DEFAULT_COMMAND_TIMEOUT

logger = logging.getLogger("vpn_manager.rasdial")

# Evita que uma janela de console pisque na tela ao executar o rasdial.
_CREATE_NO_WINDOW = 0x08000000

# Intervalo de polling ao esperar o rasdial.exe terminar: pequeno o bastante
# para que um cancelamento pedido pelo usuário responda quase instantaneamente,
# grande o bastante para não gastar CPU à toa numa operação que normalmente
# demora segundos.
_POLL_INTERVAL_SECONDS = 0.2

# Código de retorno sintético (nunca produzido pelo rasdial.exe de verdade)
# usado para marcar que a operação foi interrompida a pedido do usuário, e não
# por timeout ou erro do rasdial.
CANCELLED_RETURN_CODE = -2


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

    def _run(
        self,
        args: List[str],
        cancel_on_timeout: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> CommandResult:
        """Executa o rasdial.exe e espera terminar, com timeout e cancelamento cooperativos.

        Usa Popen + polling (em vez de subprocess.run bloqueante) para que um
        cancelamento pedido pelo usuário (`cancel_event`) consiga interromper a
        espera quase imediatamente, sem precisar aguardar o timeout completo.
        """
        start = time.perf_counter()
        try:
            proc = subprocess.Popen(
                [self.executable, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except OSError as exc:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error("Falha ao executar rasdial: %s", exc)
            return CommandResult(False, -1, "", str(exc), duration_ms)

        cancelled = False
        while True:
            try:
                raw_stdout, raw_stderr = proc.communicate(timeout=_POLL_INTERVAL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                if cancel_event is not None and cancel_event.is_set():
                    cancelled = True
                    proc.kill()
                    raw_stdout, raw_stderr = proc.communicate()
                    break
                if (time.perf_counter() - start) >= self.timeout:
                    proc.kill()
                    proc.communicate()
                    duration_ms = (time.perf_counter() - start) * 1000
                    logger.error(
                        "Tempo limite excedido ao executar rasdial (operação: %s)", args[0] if args else "status"
                    )
                    if cancel_on_timeout:
                        self._cancel_after_timeout(cancel_on_timeout)
                    return CommandResult(False, -1, "", "Tempo limite excedido", duration_ms)

        duration_ms = (time.perf_counter() - start) * 1000
        if cancelled:
            logger.info("Operação cancelada pelo usuário (operação: %s)", args[0] if args else "status")
            if cancel_on_timeout:
                self._cancel_after_timeout(cancel_on_timeout)
            return CommandResult(False, CANCELLED_RETURN_CODE, "", "Cancelado pelo usuário", duration_ms)

        stdout = raw_stdout.decode(_OUTPUT_ENCODING, errors="replace").strip()
        stderr = raw_stderr.decode(_OUTPUT_ENCODING, errors="replace").strip()
        return CommandResult(
            success=proc.returncode == 0,
            return_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_ms=duration_ms,
        )

    def _cancel_after_timeout(self, name: str) -> None:
        """Interrompe (best-effort) uma discagem cujo rasdial.exe foi encerrado por timeout.

        Matar o processo rasdial.exe não cancela a tentativa de conexão em
        andamento no serviço RAS do Windows: ela pode terminar de conectar
        segundos ou minutos depois, silenciosamente, fazendo a VPN aparecer como
        conectada mesmo após termos reportado falha ao usuário. Um /disconnect
        aqui garante que a falha reportada corresponda ao estado real.
        """
        try:
            subprocess.run(
                [self.executable, name, "/disconnect"],
                capture_output=True,
                timeout=10,
                creationflags=_CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.warning("Falha ao cancelar tentativa de conexão expirada de '%s': %s", name, exc)

    def connect(
        self,
        name: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        phonebook_path: Optional[str] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> CommandResult:
        """Conecta a uma VPN pelo nome. Credenciais, quando fornecidas, nunca são persistidas.

        Quando `phonebook_path` é informado, força o rasdial a procurar a entrada
        especificamente nesse arquivo .pbk (via `/PHONEBOOK:`), em vez de depender
        da busca padrão do Windows nos phonebooks de usuário/sistema. Isso evita
        discar a entrada errada quando existem VPNs com o mesmo nome em escopos
        diferentes, ou quando um diretório PBK customizado está configurado.
        `/DISCONNECT` não aceita `/PHONEBOOK` (confirmado em `rasdial.exe /?`), por
        isso essa opção não existe em `disconnect()`.

        `cancel_event`, quando fornecido e sinalizado durante a espera, interrompe
        a tentativa (usado pelo botão "Cancelar" na UI para uma conexão demorada).
        """
        args = [name]
        if username is not None and password is not None:
            args.extend([username, password])
        if phonebook_path:
            args.append(f"/PHONEBOOK:{phonebook_path}")
        return self._run(args, cancel_on_timeout=name, cancel_event=cancel_event)

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
