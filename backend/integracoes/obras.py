"""
Projeto do cliente a partir da planilha OBRAS (tela "Meu projeto").

- A linha do cliente é achada pelo Nº OBRA = ID do cliente (campo do cadastro).
- Só saem daqui os campos que o cliente pode ver: etapas, datas, potência, nº de módulos, cidade/UF
  e os documentos dele. Valor, vendedor, forma de pagamento, nota fiscal etc. NUNCA são enviados.
- A planilha é lida no máximo a cada 5 min (fica guardada no cache), para não estourar o limite do Google.

Regras (definidas com o responsável em 18/11/2026):
- Etapa atual = coluna ETAPA ENGENHARIA (Documentação, Homologação, Projeto, Instalação, Comissionamento);
  as anteriores estão concluídas e as seguintes, próximas.
- As colunas de data dizem quando cada coisa foi concluída.
- Prazo da vistoria = VISTORIA TÉCNICA + 7 dias úteis (Neoenergia) ou 5 (Equatorial);
  fins de semana e feriados nacionais não contam.
- Prazos previstos das etapas: regras ainda a definir (por enquanto, "a definir").
"""
import re
import unicodedata
from datetime import date, datetime, timedelta

from django.conf import settings
from django.core.cache import cache

from . import google

CHAVE_CACHE = 'planilha-obras'
VALIDADE_CACHE = 5 * 60   # segundos

# Etapas na ordem; "etapa" = valor da coluna ETAPA ENGENHARIA que indica que o cliente está nela
ETAPAS = [
    {'chave': 'onboarding', 'nome': 'Onboarding', 'etapa': 'documentacao',
     'inicio': 'FECHAMENTO', 'fim': 'DOCUMENTAÇÃO'},
    {'chave': 'homologacao', 'nome': 'Homologação', 'etapa': 'homologacao',
     'inicio': 'HOMOLOGAÇÃO (ENTRADA)', 'fim': 'APROVAÇÃO DO PROJETO'},
    {'chave': 'projeto_executivo', 'nome': 'Projeto executivo', 'etapa': 'projeto',
     'inicio': 'APROVAÇÃO DO PROJETO', 'fim': 'PROJETO'},
    {'chave': 'instalacao', 'nome': 'Instalação', 'etapa': 'instalacao',
     'inicio': 'INSTALAÇÃO (ENTRADA)', 'fim': 'INSTALAÇÃO CONCLUÍDA', 'previsao_inicio': 'INSTALAÇÃO PROGRAMADA'},
    {'chave': 'comissionamento', 'nome': 'Comissionamento e vistoria', 'etapa': 'comissionamento',
     'inicio': 'INSTALAÇÃO CONCLUÍDA', 'fim': None},
]

# Documentos: coluna da planilha com o ID do arquivo no Drive (colunas a criar na aba OBRAS)
DOCUMENTOS = {
    'art': {'etapa': 'homologacao', 'nome': 'ART', 'coluna': 'ID ART',
            'aviso': 'Disponível após o registro da ART'},
    'parecer': {'etapa': 'homologacao', 'nome': 'Parecer de Acesso', 'coluna': 'ID PARECER DE ACESSO',
                'aviso': 'Disponível após a aprovação da concessionária'},
    'prancha': {'etapa': 'projeto_executivo', 'nome': 'Prancha do projeto', 'coluna': 'ID PRANCHA',
                'aviso': 'Disponível quando o projeto for concluído'},
    'comissionamento_1': {'etapa': 'instalacao', 'nome': 'Comissionamento nível 01', 'coluna': 'ID COMISSIONAMENTO N1',
                          'aviso': 'Disponível ao fim da instalação'},
    'comissionamento_2': {'etapa': 'comissionamento', 'nome': 'Comissionamento nível 02', 'coluna': 'ID COMISSIONAMENTO N2',
                          'aviso': 'Disponível após os testes da usina'},
}

DIAS_UTEIS_VISTORIA = {'neoenergia': 7, 'equatorial': 5}


class PlanilhaIndisponivel(Exception):
    """Planilha não configurada ou o Google não respondeu (a tela mostra uma mensagem amigável)."""


# ----------------------------------------------------------------------------
# Leitura da planilha
# ----------------------------------------------------------------------------
def _simplificar(texto: str) -> str:
    """'Homologação (Entrada)' -> 'homologacao (entrada)' (para comparar sem acento/caixa)."""
    texto = unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', texto).strip().lower()


def linhas_obras() -> list[dict]:
    """Linhas da aba OBRAS como {coluna simplificada: valor}. Guardadas por 5 min."""
    linhas = cache.get(CHAVE_CACHE)
    if linhas is not None:
        return linhas
    if not google.configurado():
        raise PlanilhaIndisponivel('Planilha OBRAS não configurada (GOOGLE_CREDENCIAIS / PLANILHA_OBRAS_ID).')
    try:
        valores = google.ler_aba(settings.PLANILHA_OBRAS_ID, settings.PLANILHA_OBRAS_ABA)
    except google.GoogleErro as erro:
        raise PlanilhaIndisponivel(str(erro)) from None
    if not valores:
        return []
    cabecalho = [_simplificar(c) for c in valores[0]]
    linhas = [{coluna: (linha[i].strip() if i < len(linha) else '') for i, coluna in enumerate(cabecalho)}
              for linha in valores[1:]]
    cache.set(CHAVE_CACHE, linhas, VALIDADE_CACHE)
    return linhas


def linha_do_cliente(id_cliente: str | None) -> dict | None:
    """A linha da obra do cliente (Nº OBRA = ID do cliente), ou None."""
    if not id_cliente:
        return None
    alvo = _simplificar(id_cliente)
    for linha in linhas_obras():
        if _simplificar(linha.get('no obra') or linha.get('n obra') or '') == alvo:
            return linha
    return None


def _valor(linha: dict, coluna: str | None) -> str:
    return linha.get(_simplificar(coluna), '') if coluna else ''


# ----------------------------------------------------------------------------
# Conversões
# ----------------------------------------------------------------------------
def ler_data(texto: str) -> date | None:
    """'05/11/2026' ou '05/11/26' -> date. Qualquer outra coisa (vazio, 'OK'...) -> None."""
    texto = (texto or '').strip()
    for formato in ('%d/%m/%Y', '%d/%m/%y', '%Y-%m-%d'):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def ler_numero(texto: str) -> float | None:
    """'8,16' / '8.16' / '1.234,5' -> float."""
    texto = re.sub(r'[^\d,.\-]', '', texto or '')
    if not texto:
        return None
    if ',' in texto:
        texto = texto.replace('.', '').replace(',', '.')
    try:
        return float(texto)
    except ValueError:
        return None


def quantidade_modulos(texto: str) -> int | None:
    """'16 - 615Wp Longi' -> 16 (só a quantidade aparece para o cliente)."""
    achado = re.match(r'\s*(\d+)', texto or '')
    return int(achado.group(1)) if achado else None


def _pascoa(ano: int) -> date:
    """Domingo de Páscoa (algoritmo de Meeus/Jones/Butcher)."""
    a, b, c = ano % 19, ano // 100, ano % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    mes = (h + l_ - 7 * m + 114) // 31
    dia = (h + l_ - 7 * m + 114) % 31 + 1
    return date(ano, mes, dia)


def feriados_nacionais(ano: int) -> set[date]:
    """Feriados nacionais, mais Carnaval (seg e ter), Sexta-feira Santa e Corpus Christi."""
    pascoa = _pascoa(ano)
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    moveis = [pascoa - timedelta(days=48), pascoa - timedelta(days=47), pascoa - timedelta(days=2),
              pascoa + timedelta(days=60)]
    return {date(ano, m, d) for m, d in fixos} | set(moveis)


def somar_dias_uteis(inicio: date, dias: int) -> date:
    """inicio + N dias úteis (sem fins de semana nem feriados nacionais)."""
    atual, contados = inicio, 0
    while contados < dias:
        atual += timedelta(days=1)
        if atual.weekday() < 5 and atual not in feriados_nacionais(atual.year):
            contados += 1
    return atual


def prazo_vistoria(linha: dict) -> date | None:
    pedido = ler_data(_valor(linha, 'VISTORIA TÉCNICA'))
    distribuidora = _simplificar(_valor(linha, 'DISTRIBUIDORA'))
    dias = next((n for nome, n in DIAS_UTEIS_VISTORIA.items() if nome in distribuidora), None)
    return somar_dias_uteis(pedido, dias) if pedido and dias else None


# ----------------------------------------------------------------------------
# Projeto (o que a tela recebe)
# ----------------------------------------------------------------------------
def indice_etapa_atual(linha: dict) -> int:
    """Pela coluna ETAPA ENGENHARIA; se vier vazia/desconhecida, pela última data de conclusão preenchida."""
    etapa = _simplificar(_valor(linha, 'ETAPA ENGENHARIA'))
    for i, e in enumerate(ETAPAS):
        if etapa and etapa.startswith(e['etapa']):
            return i
    concluidas = [i for i, e in enumerate(ETAPAS) if e['fim'] and ler_data(_valor(linha, e['fim']))]
    return min(len(ETAPAS) - 1, (max(concluidas) + 1) if concluidas else 0)


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def montar_projeto(linha: dict, id_cliente: str) -> dict:
    atual = indice_etapa_atual(linha)
    vistoria = prazo_vistoria(linha)
    etapas = []
    for i, e in enumerate(ETAPAS):
        status = 'concluida' if i < atual else 'andamento' if i == atual else 'proxima'
        inicio = ler_data(_valor(linha, e['inicio']))
        fim = ler_data(_valor(linha, e['fim'])) if status == 'concluida' else None
        documentos = []
        for tipo, doc in DOCUMENTOS.items():
            if doc['etapa'] != e['chave']:
                continue
            tem_arquivo = bool(_valor(linha, doc['coluna']))
            documentos.append({'tipo': tipo, 'nome': doc['nome'], 'disponivel': tem_arquivo,
                               'aviso': '' if tem_arquivo else doc['aviso']})
        etapas.append({
            'chave': e['chave'], 'nome': e['nome'], 'status': status,
            'inicio': _iso(inicio) if status != 'proxima' else None,
            'fim': _iso(fim),
            'previsao_inicio': _iso(ler_data(_valor(linha, e.get('previsao_inicio')))) if status == 'proxima' else None,
            'previsao_fim': _iso(vistoria) if e['chave'] == 'comissionamento' else None,
            'prazo_vistoria': _iso(vistoria) if e['chave'] == 'comissionamento' else None,
            'documentos': documentos,
        })
    return {
        'id_cliente': id_cliente,
        'potencia_kwp': ler_numero(_valor(linha, 'kWp')),
        'modulos': quantidade_modulos(_valor(linha, 'MÓDULOS')),
        'cidade': _valor(linha, 'CIDADE'),
        'uf': _valor(linha, 'UF'),
        'previsao_conclusao': _iso(vistoria),
        'etapas': etapas,
    }


def id_do_arquivo(linha: dict, tipo: str) -> str | None:
    """ID no Drive do documento `tipo` DESTA linha (o cliente nunca acessa arquivo de outra obra)."""
    doc = DOCUMENTOS.get(tipo)
    return (_valor(linha, doc['coluna']) or None) if doc else None
