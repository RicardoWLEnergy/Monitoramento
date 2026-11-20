"""
Clima do dia de cada usina (Ensolarado, Nublado ou Chuvoso), pela Open-Meteo.

- Fonte: https://open-meteo.com — código de condição do tempo (padrão WMO) e chuva do dia, por latitude/longitude.
  Dias recentes e de hoje: API de previsão; dias com mais de 5 dias: API de histórico (arquivo).
- Licença: o uso GRATUITO da Open-Meteo é só para fins NÃO comerciais. Quando o sistema for vendido,
  assinar o plano comercial e preencher OPEN_METEO_CHAVE no .env (aí as chamadas vão para os endereços "customer").
- Privacidade: a localização vai arredondada (2 casas ≈ 1 km): basta para o clima e não identifica a casa.
- Usinas na mesma região (mesmas coordenadas arredondadas) compartilham a mesma consulta.
- Usina sem latitude/longitude (ex.: FoxESS, que não informa): usa as coordenadas da CIDADE (busca de cidades
  da Open-Meteo, no Brasil, conferindo o estado pela UF). Fica guardado por 30 dias e NÃO é gravado na usina.
- Falha da Open-Meteo nunca para a coleta: vira ClimaErro, registrada no log.
"""
import hashlib
import logging
import time
import unicodedata
from collections import defaultdict
from datetime import date, timedelta

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from monitoramento.models import ClimaDiario
from usinas.models import Usina

TEMPO_LIMITE = 8   # segundos por consulta: clima é informação secundária, nunca pode segurar o coletor
DIAS_ATE_O_ARQUIVO = 5          # o histórico (arquivo) da Open-Meteo chega com uns 5 dias de atraso
POR_CONSULTA = 50               # locais por chamada (a Open-Meteo aceita vários de uma vez)

# Códigos WMO de condição do tempo
CHUVA = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}
ENSOLARADO = {0, 1}             # céu limpo / poucas nuvens
CHUVA_MINIMA_MM = 1.0


class ClimaErro(Exception):
    """Falha ao consultar a Open-Meteo (mensagem técnica: vai para o registro)."""


log = logging.getLogger('coletor')
VALIDADE_CIDADE = 30 * 24 * 60 * 60   # segundos: coordenadas de cidade quase nunca mudam
ESTADOS = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas', 'BA': 'Bahia', 'CE': 'Ceará',
    'DF': 'Distrito Federal', 'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão', 'MT': 'Mato Grosso',
    'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais', 'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná',
    'PE': 'Pernambuco', 'PI': 'Piauí', 'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte',
    'RS': 'Rio Grande do Sul', 'RO': 'Rondônia', 'RR': 'Roraima', 'SC': 'Santa Catarina', 'SP': 'São Paulo',
    'SE': 'Sergipe', 'TO': 'Tocantins',
}


def _simples(texto: str) -> str:
    return unicodedata.normalize('NFKD', str(texto or '')).encode('ascii', 'ignore').decode().strip().lower()


def coordenadas_da_cidade(cidade: str, uf: str = '') -> tuple[float, float] | None:
    """Centro da cidade (Brasil) pela busca de cidades da Open-Meteo. Guardado por 30 dias (inclusive "não achou")."""
    if not (cidade or '').strip():
        return None
    uf = (uf or '').strip().upper()
    chave = 'cidade-clima:' + hashlib.md5(f'{_simples(cidade)}|{uf}'.encode()).hexdigest()
    guardado = cache.get(chave)
    if guardado is not None:
        return tuple(guardado) if guardado else None
    endereco = ('https://customer-geocoding-api.open-meteo.com/v1/search' if settings.OPEN_METEO_CHAVE
                else 'https://geocoding-api.open-meteo.com/v1/search')
    params = {'name': cidade.strip(), 'count': 10, 'language': 'pt', 'countryCode': 'BR'}
    if settings.OPEN_METEO_CHAVE:
        params['apikey'] = settings.OPEN_METEO_CHAVE
    try:
        r = requests.get(endereco, params=params, timeout=TEMPO_LIMITE)
        resultados = (r.json() or {}).get('results') or [] if r.status_code == 200 else None
    except (requests.RequestException, ValueError) as erro:
        raise ClimaErro(f'busca de cidade indisponível ({erro.__class__.__name__})') from None
    if resultados is None:
        raise ClimaErro(f'busca de cidade HTTP {r.status_code}')
    estado = _simples(ESTADOS.get(uf, ''))
    candidatos = [x for x in resultados if not estado or _simples(x.get('admin1')) == estado]
    achado = candidatos[0] if candidatos else None
    coordenadas = (round(float(achado['latitude']), 2), round(float(achado['longitude']), 2)) if achado else None
    cache.set(chave, list(coordenadas) if coordenadas else [], VALIDADE_CIDADE)
    return coordenadas


def classificar(codigo: int | None, chuva_mm: float | None) -> str:
    """Código WMO + chuva do dia -> ensolarado / nublado / chuvoso."""
    if (codigo in CHUVA) or (chuva_mm or 0) >= CHUVA_MINIMA_MM:
        return ClimaDiario.Condicao.CHUVOSO
    if codigo in ENSOLARADO:
        return ClimaDiario.Condicao.ENSOLARADO
    return ClimaDiario.Condicao.NUBLADO


def _local(usina: Usina, rodada: dict) -> tuple[float, float, str] | None:
    """Coordenadas da usina (arredondadas); sem elas, as da cidade. Na 1ª falha da busca de cidade,
    não tenta mais nesta rodada (Open-Meteo lenta não pode multiplicar a espera por usina)."""
    if usina.latitude is not None and usina.longitude is not None:
        return round(float(usina.latitude), 2), round(float(usina.longitude), 2), usina.fuso_horario
    if rodada.get('busca_falhou') or time.monotonic() > rodada['prazo']:
        return None
    try:
        cidade = coordenadas_da_cidade(usina.cidade, usina.uf)
    except ClimaErro as erro:
        rodada['busca_falhou'] = True
        log.warning('Clima: busca de cidade indisponível nesta rodada (%s)', erro)
        return None
    return (*cidade, usina.fuso_horario) if cidade else None


def _endereco(arquivo: bool) -> str:
    if settings.OPEN_METEO_CHAVE:
        return ('https://customer-archive-api.open-meteo.com/v1/archive' if arquivo
                else 'https://customer-api.open-meteo.com/v1/forecast')
    return 'https://archive-api.open-meteo.com/v1/archive' if arquivo else 'https://api.open-meteo.com/v1/forecast'


def _consultar(locais: list[tuple[float, float]], fuso: str, inicio: date, fim: date, arquivo: bool) -> list[dict]:
    params = {
        'latitude': ','.join(str(lat) for lat, _ in locais),
        'longitude': ','.join(str(lon) for _, lon in locais),
        'daily': 'weather_code,precipitation_sum', 'timezone': fuso,
        'start_date': inicio.isoformat(), 'end_date': fim.isoformat(),
    }
    if settings.OPEN_METEO_CHAVE:
        params['apikey'] = settings.OPEN_METEO_CHAVE
    try:
        r = requests.get(_endereco(arquivo), params=params, timeout=TEMPO_LIMITE)
    except requests.RequestException as erro:
        raise ClimaErro(f'sem conexão com a Open-Meteo ({erro.__class__.__name__})') from None
    try:
        dados = r.json()
    except ValueError:
        dados = {}
    if r.status_code != 200:
        motivo = dados.get('reason') if isinstance(dados, dict) else ''
        raise ClimaErro(f'Open-Meteo HTTP {r.status_code}: {motivo or "erro desconhecido"}')
    return dados if isinstance(dados, list) else [dados]   # 1 local = objeto; vários = lista na mesma ordem


def atualizar_clima(usinas, inicio: date, fim: date, segundos: float = 60) -> int:
    """
    Busca e grava o clima de cada usina entre `inicio` e `fim`. Devolve os registros gravados.
    `segundos` é o prazo da rodada: passou dele, para (o resto fica para a próxima). Grava a cada consulta,
    então uma falha no meio não perde o que já veio.
    """
    rodada = {'prazo': time.monotonic() + segundos}
    hoje = timezone.localdate()
    fim = min(fim, hoje)
    if inicio > fim:
        return 0
    corte = hoje - timedelta(days=DIAS_ATE_O_ARQUIVO)
    trechos = []                                        # (início, fim, usa o arquivo?)
    if inicio < corte:
        trechos.append((inicio, min(fim, corte - timedelta(days=1)), True))
    if fim >= corte:
        trechos.append((max(inicio, corte), fim, False))

    por_local: dict[tuple, list[Usina]] = defaultdict(list)
    for usina in usinas:
        if local := _local(usina, rodada):
            por_local[local].append(usina)

    por_fuso: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for lat, lon, fuso in por_local:
        por_fuso[fuso].append((lat, lon))

    gravados = 0
    for fuso, locais in por_fuso.items():
        for i in range(0, len(locais), POR_CONSULTA):
            lote = locais[i:i + POR_CONSULTA]
            for de, ate, arquivo in trechos:
                if time.monotonic() > rodada['prazo']:
                    log.warning('Clima: prazo da rodada esgotado; o restante fica para a próxima.')
                    return gravados
                registros = []
                for (lat, lon), resposta in zip(lote, _consultar(lote, fuso, de, ate, arquivo)):
                    diario = (resposta.get('daily') if isinstance(resposta, dict) else None) or {}
                    for dia, codigo, chuva in zip(diario.get('time') or [], diario.get('weather_code') or [],
                                                  diario.get('precipitation_sum') or []):
                        if codigo is None and chuva is None:
                            continue
                        for usina in por_local[(lat, lon, fuso)]:
                            registros.append(ClimaDiario(
                                usina=usina, data=date.fromisoformat(dia), codigo=codigo,
                                chuva_mm=round(float(chuva or 0), 1), condicao=classificar(codigo, chuva)))
                if registros:
                    ClimaDiario.objects.bulk_create(
                        registros, update_conflicts=True, unique_fields=['usina', 'data'],
                        update_fields=['codigo', 'chuva_mm', 'condicao', 'atualizado_em'])
                    gravados += len(registros)
    return gravados


def clima_por_dia(usina: Usina, inicio: date, fim: date) -> dict[date, dict]:
    """{data: {'condicao': 'ensolarado', 'chuva_mm': 0.0}} já gravado para a usina."""
    return {c.data: {'condicao': c.condicao, 'chuva_mm': c.chuva_mm}
            for c in ClimaDiario.objects.filter(usina=usina, data__gte=inicio, data__lte=fim)}
