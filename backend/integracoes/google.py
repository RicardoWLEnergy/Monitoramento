"""
Acesso ao Google (planilha OBRAS e arquivos do Drive) com uma CONTA DE SERVIÇO da empresa.

- A conta de serviço é um "usuário robô": a planilha e a pasta dos documentos são compartilhadas
  com o e-mail dela (como Leitor). Ela só lê; nunca altera nada.
- Credencial no .env (GOOGLE_CREDENCIAIS): o conteúdo do arquivo JSON da chave, em base64
  (ou o próprio JSON). Nunca vai para o git nem para o registro (log).
- APIs usadas (REST, sem bibliotecas extras além do google-auth):
  Sheets  GET https://sheets.googleapis.com/v4/spreadsheets/{id}/values/{aba}
  Drive   GET https://www.googleapis.com/drive/v3/files/{id}  (?alt=media para o conteúdo)
"""
import base64
import json
from dataclasses import dataclass

import requests
from django.conf import settings

ESCOPOS = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
]
TEMPO_LIMITE = 30
LIMITE_ARQUIVO = 30 * 1024 * 1024   # 30 MB: maior que isso não é entregue pelo sistema


class GoogleErro(Exception):
    """Falha ao falar com o Google (mensagem técnica: vai para o registro, não para a tela)."""


class ArquivoGrande(GoogleErro):
    """Documento acima de LIMITE_ARQUIVO."""


def configurado() -> bool:
    return bool(settings.GOOGLE_CREDENCIAIS and settings.PLANILHA_OBRAS_ID)


def _sessao():
    """Sessão HTTP autenticada com a conta de serviço (o token é renovado sozinho)."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    bruto = settings.GOOGLE_CREDENCIAIS.strip()
    try:
        texto = bruto if bruto.startswith('{') else base64.b64decode(bruto).decode('utf-8')
        info = json.loads(texto)
        credenciais = service_account.Credentials.from_service_account_info(info, scopes=ESCOPOS)
    except (ValueError, KeyError) as erro:
        raise GoogleErro(f'GOOGLE_CREDENCIAIS inválida ({erro.__class__.__name__}).') from None
    return AuthorizedSession(credenciais)


def _get(sessao, url: str, stream: bool = False, **params):
    from google.auth.exceptions import GoogleAuthError
    try:
        r = sessao.get(url, params=params, timeout=TEMPO_LIMITE, stream=stream)
    except requests.RequestException as erro:
        raise GoogleErro(f'sem conexão com o Google ({erro.__class__.__name__})') from None
    except GoogleAuthError as erro:   # chave revogada/apagada, relógio errado, falha ao renovar o token
        raise GoogleErro(f'autenticação no Google recusada ({erro.__class__.__name__}): confira a chave da conta de serviço') from None
    if r.status_code != 200:
        r.close()
        raise GoogleErro(f'Google HTTP {r.status_code}: {_mensagem(r)}')
    return r


def _em_partes(resposta, tamanho: int = 64 * 1024):
    """Entrega o arquivo aos poucos e sempre fecha a conexão com o Google (mesmo se o cliente desistir)."""
    try:
        yield from resposta.iter_content(tamanho)
    finally:
        resposta.close()


def ler_aba(planilha_id: str, aba: str) -> list[list[str]]:
    """Todas as linhas da aba, como texto (do jeito que aparecem na planilha). A 1ª linha é o cabeçalho."""
    r = _get(_sessao(), f'https://sheets.googleapis.com/v4/spreadsheets/{planilha_id}/values/{aba}',
             valueRenderOption='FORMATTED_VALUE')
    return r.json().get('values', [])


@dataclass
class Arquivo:
    nome: str
    tipo: str            # content-type (ex.: application/pdf)
    conteudo: object     # pedaços (bytes) entregues aos poucos, sem carregar o arquivo inteiro na memória


def baixar_arquivo(arquivo_id: str) -> Arquivo:
    """Baixa um arquivo do Drive. Documentos do Google (Docs/Planilhas) são convertidos para PDF."""
    base = f'https://www.googleapis.com/drive/v3/files/{arquivo_id}'
    sessao = _sessao()
    info = _get(sessao, base, fields='name,mimeType,size', supportsAllDrives='true').json()
    nome, tipo = info.get('name') or 'documento', info.get('mimeType') or 'application/octet-stream'
    if int(info.get('size') or 0) > LIMITE_ARQUIVO:
        raise ArquivoGrande(f'arquivo {arquivo_id} com {int(info["size"]) // 1_048_576} MB (limite 30 MB)')
    if tipo.startswith('application/vnd.google-apps'):
        r = _get(sessao, f'{base}/export', stream=True, mimeType='application/pdf')
        nome, tipo = (nome if nome.lower().endswith('.pdf') else f'{nome}.pdf'), 'application/pdf'
    else:
        r = _get(sessao, base, stream=True, alt='media', supportsAllDrives='true')
    return Arquivo(nome=nome, tipo=tipo, conteudo=_em_partes(r))


def _mensagem(resposta) -> str:
    try:
        return resposta.json().get('error', {}).get('message', '') or 'erro desconhecido'
    except ValueError:
        return 'erro desconhecido'
