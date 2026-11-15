"""
Cliente da uazapi (WhatsApp) — por enquanto só o envio de texto (código de acesso no login).

Documentação oficial: https://docs.uazapi.com/reference/sendText.md
- POST {UAZAPI_URL}/send/text, cabeçalho "token" = token da INSTÂNCIA (não o admintoken).
- Corpo: {"number": "5561999998888", "text": "..."} — número só com dígitos, com o código do país.
- Erros: 400 dados inválidos · 401 token inválido · 429 limite de chamadas · 500 falha no envio
  (inclui o bloqueio temporário do WhatsApp para conversas novas, código 463).
O token nunca vai para o registro (log) nem para as mensagens de erro.
"""
import re

import requests
from django.conf import settings


class UazapiErro(Exception):
    """Falha no envio pela uazapi (a mensagem é técnica: vai para o registro do servidor, não para a tela)."""


def configurado() -> bool:
    return bool(settings.UAZAPI_URL and settings.UAZAPI_TOKEN)


def enviar_texto(numero: str, texto: str, timeout: int = 15) -> dict:
    """Envia uma mensagem de texto. Devolve a resposta da uazapi; levanta UazapiErro se não enviar."""
    if not configurado():
        raise UazapiErro('Envio por WhatsApp não configurado (UAZAPI_URL e UAZAPI_TOKEN no .env).')
    try:
        resposta = requests.post(
            settings.UAZAPI_URL.rstrip('/') + '/send/text',
            json={'number': re.sub(r'\D', '', numero), 'text': texto},
            headers={'token': settings.UAZAPI_TOKEN, 'Accept': 'application/json'},
            timeout=timeout,
        )
    except requests.RequestException as erro:
        raise UazapiErro(f'sem conexão com a uazapi ({erro.__class__.__name__})') from None

    if resposta.status_code != 200:
        try:
            corpo = resposta.json()
        except ValueError:
            corpo = {}
        detalhe = corpo.get('message') or corpo.get('error') or 'erro desconhecido'
        raise UazapiErro(f'uazapi HTTP {resposta.status_code}: {detalhe}')
    try:
        return resposta.json()
    except ValueError:
        return {}
