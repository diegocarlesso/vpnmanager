"""Interpretação de códigos de erro numéricos do Windows RAS.

O rasdial.exe imprime mensagens localizadas no formato "Erro <código> de Acesso
Remoto - <descrição>" (ou "Error <code>..." em inglês). O texto da descrição
muda com o idioma do Windows, mas o código numérico é estável — por isso ele é
a base mais confiável para decidir o que aconteceu (ex.: foi credencial
inválida ou foi rede/firewall) em vez de procurar palavras-chave localizadas.
"""
from __future__ import annotations

import re
from typing import Optional

_ERROR_CODE_PATTERN = re.compile(r"(?:Erro|Error)\s+(\d{2,5})", re.IGNORECASE)

# Cobre os códigos mais comuns citados por suporte corporativo de VPN. Não é
# exaustivo: códigos ausentes simplesmente caem no texto bruto do rasdial.
_RAS_ERROR_DESCRIPTIONS = {
    "623": "Entrada de VPN não encontrada no catálogo telefônico.",
    "628": "A conexão foi encerrada.",
    "629": "A conexão foi encerrada pelo computador remoto.",
    "633": "A porta ou dispositivo já está em uso por outra conexão.",
    "651": "O dispositivo de conexão relatou um erro.",
    "691": "Usuário ou senha inválidos.",
    "789": "Falha na negociação L2TP/IPsec (verifique a chave pré-compartilhada ou o certificado).",
    "809": "Não foi possível estabelecer a conexão (rede, firewall ou NAT pode estar bloqueando a porta VPN).",
    "868": "Não foi possível resolver o servidor VPN (problema de DNS ou endereço incorreto).",
}

# Código RAS que indica especificamente credencial inválida: usado para decidir
# com confiança quando reabrir o diálogo de usuário/senha.
CREDENTIAL_ERROR_CODE = "691"


def extract_ras_error_code(text: str) -> Optional[str]:
    """Extrai o código numérico de uma mensagem de erro do rasdial, se houver."""
    match = _ERROR_CODE_PATTERN.search(text)
    return match.group(1) if match else None


def describe_ras_error(text: str) -> Optional[str]:
    """Retorna uma descrição curta e estável (independente de idioma) para o
    código RAS embutido em `text`, ou None se o código não for reconhecido."""
    code = extract_ras_error_code(text)
    if code is None:
        return None
    return _RAS_ERROR_DESCRIPTIONS.get(code)
