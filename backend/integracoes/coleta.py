"""
Coleta de dados das usinas cadastradas (FoxESS).

- atualizar_tempo_real(): potência atual, energia de hoje e estado de cada inversor
- importar_geracao_diaria(): energia de cada dia de um período (relatório mensal da FoxESS)
- importar_curvas(): potência a cada 5 min de um período (histórico da FoxESS, 1 dia por chamada)
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


def amostra_por_bloco(pontos: list[tuple[datetime, float]]) -> dict[datetime, float]:
    """
    Pontos de UM inversor → um valor por bloco de 5 min: a amostra REAL mais próxima do horário
    do bloco (sem somar nem tirar média), para bater com o portal do fabricante.
    Ex.: 06:28:40 (5,0 kW) e 06:32:10 (6,2 kW) caem no bloco 06:30 → fica 5,0 kW.
    """
    melhor: dict[datetime, tuple[float, float]] = {}
    for momento, valor in pontos:
        bloco = arredondar_5min(momento)
        distancia = abs((momento - bloco).total_seconds())
        if bloco not in melhor or distancia < melhor[bloco][0]:
            melhor[bloco] = (distancia, valor)
    return {bloco: valor for bloco, (_, valor) in melhor.items()}


def _numero(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


# Período sem sol (horário local da usina). Sem geração nesse período é normal: status "noite".
INICIO_NOITE, FIM_NOITE = 18, 6


def e_noite(momento: datetime, fuso: str) -> bool:
    hora = momento.astimezone(ZoneInfo(fuso)).hour
    return hora >= INICIO_NOITE or hora < FIM_NOITE


def _status_inversor(estado, potencia: float, noite: bool = False) -> str:
    try:
        estado = int(estado)
    except (TypeError, ValueError):
        estado = None
    if estado in ESTADOS_FALHA:
        return Status.ALERTA                 # falha é alerta a qualquer hora
    if estado in ESTADOS_ONLINE or potencia > 0:
        return Status.ONLINE
    return Status.NOITE if noite else Status.OFFLINE   # inversor desligado sem sol não é problema


def _usinas_foxess(usinas=None):
    qs = usinas if usinas is not None else Usina.objects.all()
    return qs.ativas().filter(plataforma=Plataforma.FOXESS).prefetch_related('inversores')


# ----------------------------------------------------------------------------
# Tempo real
# ----------------------------------------------------------------------------
def sem_comunicacao(inv: Inversor, usina: Usina, agora: datetime) -> None:
    """
    Inversor sem leitura recente (mais velha que "considerar offline após"): não mantém a última
    potência congelada. Potência vai a zero; a energia de hoje só fica se a última leitura for de hoje.
    Status: "Sem sol" à noite (e no começo da manhã, enquanto o inversor ainda não acordou), senão offline.
    """
    fuso = ZoneInfo(usina.fuso_horario)
    inv.potencia_atual_kw = 0
    if not inv.ultima_leitura or inv.ultima_leitura.astimezone(fuso).date() != agora.astimezone(fuso).date():
        inv.geracao_hoje_kwh = 0
    hora = agora.astimezone(fuso).hour
    acordando = FIM_NOITE <= hora < FIM_NOITE + 2 and inv.status == Status.NOITE
    inv.status = Status.NOITE if e_noite(agora, usina.fuso_horario) or acordando else Status.OFFLINE


def leitura_recente(momento: datetime | None, usina: Usina, agora: datetime) -> bool:
    """Leitura dentro do prazo "considerar offline após" (e sem relógio adiantado do inversor)."""
    if momento is None or momento > agora + timedelta(hours=1):
        return False
    return agora - momento <= timedelta(minutes=usina.minutos_sem_comunicacao or 60)


def atualizar_tempo_real(usinas=None, api: FoxESSCliente | None = None) -> Relatorio:
    """Atualiza inversores e usinas; grava a leitura atual e a energia de hoje."""
    api = api or cliente_foxess()
    rel = Relatorio()
    usinas = list(_usinas_foxess(usinas))
    numeros = sorted(inv.numero_serie for u in usinas for inv in u.inversores.all())
    if not numeros:
        return rel

    dados = {d.get('deviceSN'): d for d in api.tempo_real(numeros) or [] if d}
    criar_particoes()   # garante a gaveta do mês atual
    agora = timezone.now()

    for usina in usinas:
        try:
            with transaction.atomic():   # uma usina com problema não desfaz as outras
                _tempo_real_da_usina(usina, dados, agora, rel)
        except Exception as erro:   # noqa: BLE001
            rel.falhas.append(f'{usina.nome}: {erro}')
    return rel


def _tempo_real_da_usina(usina: Usina, dados: dict, agora: datetime, rel: Relatorio) -> None:
    lista = list(usina.inversores.all())
    for inv in lista:
        d = dados.get(inv.numero_serie)
        if not d:
            rel.falhas.append(f'{inv.numero_serie}: sem resposta no tempo real')
        momento = horario_foxess(d.get('time')) if d else None
        if d and leitura_recente(momento, usina, agora):
            v = {item.get('variable'): item.get('value') for item in d.get('datas') or [] if item}
            potencia = _numero(v.get('generationPower'))
            inv.potencia_atual_kw = round(potencia, 3)
            inv.geracao_hoje_kwh = round(_numero(v.get('todayYield')), 3)
            inv.status = _status_inversor(v.get('runningState'), potencia, e_noite(momento, usina.fuso_horario))
            inv.ultima_leitura = momento
        else:
            sem_comunicacao(inv, usina, agora)
        inv.save(update_fields=['potencia_atual_kw', 'geracao_hoje_kwh', 'status', 'ultima_leitura'])
        rel.inversores += 1

    usina.status = status_da_usina([i.status for i in lista])
    recentes = [i.ultima_leitura for i in lista if leitura_recente(i.ultima_leitura, usina, agora)]
    if recentes:
        usina.ultima_leitura = max(recentes)
    usina.save(update_fields=['status', 'ultima_leitura', 'atualizado_em'])

    if recentes:
        fuso = ZoneInfo(usina.fuso_horario)
        hoje = max(recentes).astimezone(fuso).date()
        Leitura.objects.bulk_create(
            [Leitura(usina=usina, data_hora=arredondar_5min(max(recentes)),
                     potencia_kw=round(sum(float(i.potencia_atual_kw) for i in lista), 3))],
            update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
        )
        rel.leituras += 1
        # Energia de hoje: só inversores com leitura de hoje (valor de ontem não entra)
        _gravar_dias(usina, {hoje: sum(float(i.geracao_hoje_kwh) for i in lista
                                       if i.ultima_leitura and i.ultima_leitura.astimezone(fuso).date() == hoje)})


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


def desde_o_inicio(usina: Usina, inicio: date) -> date:
    """A importação nunca vai antes do início da operação (antes dele tudo seria zero)."""
    return max(inicio, usina.inicio_operacao) if usina.inicio_operacao else inicio


def _desde_a_primeira_geracao(usina: Usina, por_dia: dict[date, float]) -> dict[date, float]:
    """
    Descarta os dias de ANTES da usina operar e mantém os zeros depois (dias parados são informação).
    - Com o início da operação cadastrado: corta nele.
    - Sem ele: corta antes da 1ª geração (considerando o que já está no banco, porque a importação
      vem em pedaços de 1 mês).
    """
    if usina.inicio_operacao:
        return {d: kwh for d, kwh in por_dia.items() if d >= usina.inicio_operacao}
    candidatos = [d for d, kwh in por_dia.items() if kwh > 0]
    primeira_no_banco = (GeracaoDiaria.objects.filter(usina=usina, energia_kwh__gt=0)
                         .aggregate(primeira=Min('data'))['primeira'])
    if primeira_no_banco:
        candidatos.append(primeira_no_banco)
    if not candidatos:
        return {}
    corte = min(candidatos)
    return {d: kwh for d, kwh in por_dia.items() if d >= corte}


def _gravar_dias(usina: Usina, energia_por_dia: dict[date, float]) -> int:
    objetos = [GeracaoDiaria(usina=usina, data=d, energia_kwh=round(kwh, 3)) for d, kwh in energia_por_dia.items()]
    GeracaoDiaria.objects.bulk_create(objetos, update_conflicts=True,
                                      unique_fields=['usina', 'data'], update_fields=['energia_kwh'])
    return len(objetos)


def importar_geracao_diaria(usina: Usina, inicio: date, fim: date, api: FoxESSCliente | None = None) -> Relatorio:
    """Energia de cada dia entre `inicio` e `fim` (1 chamada por inversor por mês), somando os inversores."""
    api = api or cliente_foxess()
    rel = Relatorio()
    inicio, fim = desde_o_inicio(usina, inicio), min(fim, timezone.localdate())
    if inicio > fim:
        return rel
    por_dia: dict[date, float] = defaultdict(float)
    meses_com_falha: set[tuple[int, int]] = set()

    for inv in usina.inversores.all():
        for ano, mes in _meses_do_periodo(inicio, fim):
            try:
                resposta = api.relatorio_mensal(inv.numero_serie, ano, mes)
            except FoxESSErro as erro:
                rel.falhas.append(f'{inv.numero_serie} {mes:02d}/{ano}: {erro}')
                meses_com_falha.add((ano, mes))
                continue
            valores = next((r.get('values') or [] for r in resposta or [] if r.get('variable') == 'generation'), [])
            for indice, kwh in enumerate(valores):
                try:
                    dia = date(ano, mes, indice + 1)
                except ValueError:
                    continue          # ex.: dia 31 em mês de 30
                if inicio <= dia <= fim:
                    por_dia[dia] += _numero(kwh)

    # Mês em que algum inversor falhou não é gravado: a soma sem ele ficaria menor que a real
    # e apagaria o valor certo já guardado (tenta de novo na próxima rotina/importação)
    por_dia = {d: kwh for d, kwh in por_dia.items() if (d.year, d.month) not in meses_com_falha}
    por_dia = _desde_a_primeira_geracao(usina, por_dia)
    if por_dia:
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
    inicio, fim = max(desde_o_inicio(usina, inicio), limite_curvas()), min(fim, timezone.localdate())
    criar_particoes(meses_antes=settings.LEITURAS_RETENCAO_MESES - 1)

    dia = fim
    while dia >= inicio:
        comeco = datetime(dia.year, dia.month, dia.day, tzinfo=fuso)
        soma: dict[datetime, float] = defaultdict(float)
        falhou = False
        for inv in usina.inversores.all():
            try:
                resposta = api.historico(inv.numero_serie, comeco, comeco + timedelta(days=1))
            except FoxESSErro as erro:
                rel.falhas.append(f'{inv.numero_serie} {dia:%d/%m}: {erro}')
                falhou = True
                continue
            pontos = []
            for serie in (resposta or [{}])[0].get('datas', []):
                if serie.get('variable') != 'generationPower':
                    continue
                for ponto in serie.get('data') or []:
                    momento = horario_foxess(ponto.get('time'))
                    if momento:
                        pontos.append((momento, _numero(ponto.get('value'))))
            # Uma amostra real por bloco para ESTE inversor; depois soma os inversores da usina
            for bloco, valor in amostra_por_bloco(pontos).items():
                soma[bloco] += valor
        # Dia com inversor faltando não substitui a curva já guardada; dia todo zerado (a usina ainda não
        # operava) não é gravado: seriam 288 leituras inúteis por dia
        if soma and not falhou and max(soma.values()) > 0:
            Leitura.objects.bulk_create(
                [Leitura(usina=usina, data_hora=m, potencia_kw=round(kw, 3)) for m, kw in soma.items()],
                update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
            )
            rel.leituras += len(soma)
            rel.dias += 1
        dia -= timedelta(days=1)
    return rel


# ----------------------------------------------------------------------------
# Cobertura (o que já existe no banco)
# ----------------------------------------------------------------------------
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
