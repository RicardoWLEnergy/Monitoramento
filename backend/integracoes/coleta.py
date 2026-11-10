"""
Coleta de dados das usinas cadastradas (FoxESS).

- atualizar_tempo_real(): potência atual, energia de hoje e estado de cada inversor
- importar_geracao_diaria(): energia de cada dia de um período (relatório mensal da FoxESS)
- importar_curvas(): potência a cada 5 min de um período (histórico da FoxESS, 1 dia por chamada)
- importar_periodo(): tudo acima de uma vez (botão "Importar histórico" e comando)
- cobertura(): o que já existe no banco para uma usina

Tudo pode ser repetido sem duplicar: leituras e dias já gravados são atualizados.
A FoxESS não tem dados por usina — tudo vem por inversor e é SOMADO por usina aqui.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Min
from django.db.models.functions import TruncDate
from django.utils import timezone

from monitoramento.models import GeracaoDiaria, Leitura
from monitoramento.particoes import criar_particoes
from usinas.models import Inversor, Plataforma, Status, Usina

from .cadastro import status_da_usina
from .foxess import FoxESSCliente, FoxESSErro

# runningState da FoxESS -> nosso status
ESTADOS_ONLINE = {163, 164}          # conectado à rede / fora da rede (gerando)
ESTADOS_FALHA = {165, 166}           # falha / falha permanente


@dataclass
class Relatorio:
    """Resumo do que foi feito, para mostrar no terminal."""
    inversores: int = 0
    leituras: int = 0
    dias: int = 0
    falhas: list[str] = field(default_factory=list)


def cliente_foxess() -> FoxESSCliente:
    return FoxESSCliente(settings.FOXESS_API_URL, settings.FOXESS_API_KEY)


def horario_foxess(texto: str | None) -> datetime | None:
    """'2026-11-09 10:04:58 BRT-0300' -> datetime com fuso."""
    if not texto:
        return None
    partes = texto.split()
    try:
        return datetime.strptime(f'{partes[0]} {partes[1]} {partes[-1][-5:]}', '%Y-%m-%d %H:%M:%S %z')
    except (ValueError, IndexError):
        return None


def arredondar_5min(momento: datetime) -> datetime:
    """10:04:58 -> 10:05 · 10:22:10 -> 10:20 (alinha os inversores para poder somar)."""
    base = momento.replace(second=0, microsecond=0)
    minutos = base.minute + (1 if momento.second >= 30 else 0)
    return base.replace(minute=0) + timedelta(minutes=round(minutos / 5) * 5)


def _numero(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def _status_inversor(estado, potencia: float) -> str:
    try:
        estado = int(estado)
    except (TypeError, ValueError):
        estado = None
    if estado in ESTADOS_FALHA:
        return Status.ALERTA
    if estado in ESTADOS_ONLINE or potencia > 0:
        return Status.ONLINE
    return Status.OFFLINE   # inclui a noite (inversor desligado sem sol)


def _usinas_foxess(usinas=None):
    qs = usinas if usinas is not None else Usina.objects.all()
    return qs.ativas().filter(plataforma=Plataforma.FOXESS).prefetch_related('inversores')


# ----------------------------------------------------------------------------
# Tempo real
# ----------------------------------------------------------------------------
def atualizar_tempo_real(usinas=None, api: FoxESSCliente | None = None) -> Relatorio:
    """Atualiza inversores e usinas; grava a leitura atual e a energia de hoje."""
    api = api or cliente_foxess()
    rel = Relatorio()
    usinas = list(_usinas_foxess(usinas))
    inversores = {inv.numero_serie: inv for u in usinas for inv in u.inversores.all()}
    if not inversores:
        return rel

    dados = {d['deviceSN']: d for d in api.tempo_real(sorted(inversores))}
    criar_particoes()   # garante a gaveta do mês atual

    with transaction.atomic():
        for sn, inv in inversores.items():
            d = dados.get(sn)
            if not d:
                rel.falhas.append(f'{sn}: sem resposta no tempo real')
                continue
            v = {item['variable']: item.get('value') for item in d.get('datas', [])}
            potencia = _numero(v.get('generationPower'))
            inv.potencia_atual_kw = round(potencia, 3)
            inv.geracao_hoje_kwh = round(_numero(v.get('todayYield')), 3)
            inv.status = _status_inversor(v.get('runningState'), potencia)
            inv.ultima_leitura = horario_foxess(d.get('time')) or inv.ultima_leitura
            inv.save(update_fields=['potencia_atual_kw', 'geracao_hoje_kwh', 'status', 'ultima_leitura'])
            rel.inversores += 1

        for usina in usinas:
            lista = [inversores[i.numero_serie] for i in usina.inversores.all()]
            horarios = [i.ultima_leitura for i in lista if i.ultima_leitura]
            usina.status = status_da_usina([i.status for i in lista])
            usina.ultima_leitura = max(horarios) if horarios else usina.ultima_leitura
            usina.save(update_fields=['status', 'ultima_leitura', 'atualizado_em'])

            if horarios:
                agora = arredondar_5min(max(horarios))
                Leitura.objects.bulk_create(
                    [Leitura(usina=usina, data_hora=agora, potencia_kw=round(sum(float(i.potencia_atual_kw) for i in lista), 3))],
                    update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
                )
                rel.leituras += 1
                hoje = max(horarios).astimezone(ZoneInfo(usina.fuso_horario)).date()
                _gravar_dias(usina, {hoje: sum(float(i.geracao_hoje_kwh) for i in lista)})
    return rel


# ----------------------------------------------------------------------------
# Geração diária (histórico)
# ----------------------------------------------------------------------------
def _meses_do_periodo(inicio: date, fim: date) -> list[tuple[int, int]]:
    """[(ano, mês), ...] de todos os meses que o período toca."""
    meses, atual = [], date(inicio.year, inicio.month, 1)
    while atual <= fim:
        meses.append((atual.year, atual.month))
        atual = date(atual.year + (atual.month == 12), atual.month % 12 + 1, 1)
    return meses


def _gravar_dias(usina: Usina, energia_por_dia: dict[date, float]) -> int:
    objetos = [GeracaoDiaria(usina=usina, data=d, energia_kwh=round(kwh, 3)) for d, kwh in energia_por_dia.items()]
    GeracaoDiaria.objects.bulk_create(objetos, update_conflicts=True,
                                      unique_fields=['usina', 'data'], update_fields=['energia_kwh'])
    return len(objetos)


def importar_geracao_diaria(usina: Usina, inicio: date, fim: date, api: FoxESSCliente | None = None) -> Relatorio:
    """Energia de cada dia entre `inicio` e `fim` (1 chamada por inversor por mês), somando os inversores."""
    api = api or cliente_foxess()
    rel = Relatorio()
    fim = min(fim, timezone.localdate())
    por_dia: dict[date, float] = defaultdict(float)

    for inv in usina.inversores.all():
        for ano, mes in _meses_do_periodo(inicio, fim):
            try:
                resposta = api.relatorio_mensal(inv.numero_serie, ano, mes)
            except FoxESSErro as erro:
                rel.falhas.append(f'{inv.numero_serie} {mes:02d}/{ano}: {erro}')
                continue
            valores = next((r.get('values') or [] for r in resposta or [] if r.get('variable') == 'generation'), [])
            for indice, kwh in enumerate(valores):
                try:
                    dia = date(ano, mes, indice + 1)
                except ValueError:
                    continue          # ex.: dia 31 em mês de 30
                if inicio <= dia <= fim:
                    por_dia[dia] += _numero(kwh)

    # Ignora os zeros antes do primeiro dia com geração (antes da usina existir)
    com_geracao = sorted(d for d, kwh in por_dia.items() if kwh > 0)
    if com_geracao:
        por_dia = {d: kwh for d, kwh in por_dia.items() if d >= com_geracao[0]}
        rel.dias = _gravar_dias(usina, por_dia)
    return rel


# ----------------------------------------------------------------------------
# Curvas de 5 minutos (histórico)
# ----------------------------------------------------------------------------
def limite_curvas() -> date:
    """Dia mais antigo de curva que o banco guarda (prazo de retenção das leituras)."""
    hoje = timezone.localdate()
    total = hoje.year * 12 + hoje.month - 1 - (settings.LEITURAS_RETENCAO_MESES - 1)
    return date(total // 12, total % 12 + 1, 1)


def importar_curvas(usina: Usina, inicio: date, fim: date, api: FoxESSCliente | None = None) -> Relatorio:
    """Potência a cada 5 min entre `inicio` e `fim` (1 chamada por inversor por dia)."""
    api = api or cliente_foxess()
    rel = Relatorio()
    fuso = ZoneInfo(usina.fuso_horario)
    inicio, fim = max(inicio, limite_curvas()), min(fim, timezone.localdate())
    criar_particoes(meses_antes=settings.LEITURAS_RETENCAO_MESES - 1)

    dia = fim
    while dia >= inicio:
        comeco = datetime(dia.year, dia.month, dia.day, tzinfo=fuso)
        soma: dict[datetime, float] = defaultdict(float)
        for inv in usina.inversores.all():
            try:
                resposta = api.historico(inv.numero_serie, comeco, comeco + timedelta(days=1))
            except FoxESSErro as erro:
                rel.falhas.append(f'{inv.numero_serie} {dia:%d/%m}: {erro}')
                continue
            for serie in (resposta or [{}])[0].get('datas', []):
                if serie.get('variable') != 'generationPower':
                    continue
                for ponto in serie.get('data') or []:
                    momento = horario_foxess(ponto.get('time'))
                    if momento:
                        soma[arredondar_5min(momento)] += _numero(ponto.get('value'))
        if soma:
            Leitura.objects.bulk_create(
                [Leitura(usina=usina, data_hora=m, potencia_kw=round(kw, 3)) for m, kw in soma.items()],
                update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
            )
            rel.leituras += len(soma)
            rel.dias += 1
        dia -= timedelta(days=1)
    return rel


# ----------------------------------------------------------------------------
# Período completo (usado pelo botão "Importar histórico" e pelo comando)
# ----------------------------------------------------------------------------
def importar_periodo(usina: Usina, inicio: date, fim: date, curvas: bool = True) -> dict:
    """Tempo real + energia diária + (opcional) curvas do período, na plataforma da usina. Devolve um resumo."""
    if usina.plataforma == Plataforma.FOXESS:
        api = cliente_foxess()
        modulo_tempo_real, modulo_diaria, modulo_curvas = atualizar_tempo_real, importar_geracao_diaria, importar_curvas
    elif usina.plataforma == Plataforma.HUAWEI:
        from . import coleta_huawei   # import aqui: coleta_huawei também importa deste módulo
        api = coleta_huawei.cliente_huawei()
        modulo_tempo_real = coleta_huawei.atualizar_tempo_real
        modulo_diaria, modulo_curvas = coleta_huawei.importar_geracao_diaria, coleta_huawei.importar_curvas
    else:
        raise ValueError(f'Plataforma sem importação de histórico: {usina.plataforma}')

    modulo_tempo_real(Usina.objects.filter(pk=usina.pk), api=api)
    diaria = modulo_diaria(usina, inicio, fim, api=api)
    curva = modulo_curvas(usina, inicio, fim, api=api) if curvas else Relatorio()
    return {
        'dias_energia': diaria.dias,
        'dias_curva': curva.dias,
        'leituras': curva.leituras,
        'falhas': (diaria.falhas + curva.falhas)[:20],
    }


def cobertura(usina: Usina) -> dict:
    """O que já existe no banco para a usina (para saber o que falta importar)."""
    dias = GeracaoDiaria.objects.filter(usina=usina).aggregate(inicio=Min('data'), fim=Max('data'), total=Count('data'))
    fuso = ZoneInfo(usina.fuso_horario)
    leituras = Leitura.objects.filter(usina=usina).aggregate(inicio=Min('data_hora'), fim=Max('data_hora'))
    dias_curva = (Leitura.objects.filter(usina=usina).annotate(dia=TruncDate('data_hora', tzinfo=fuso))
                  .values('dia').distinct().count())
    return {
        'energia_diaria': {'inicio': dias['inicio'], 'fim': dias['fim'], 'dias': dias['total']},
        'curvas': {
            'inicio': leituras['inicio'].astimezone(fuso).date() if leituras['inicio'] else None,
            'fim': leituras['fim'].astimezone(fuso).date() if leituras['fim'] else None,
            'dias': dias_curva,
        },
        'limite_curvas': limite_curvas(),
        'inversores': usina.inversores.count(),
    }
