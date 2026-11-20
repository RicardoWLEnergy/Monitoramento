"""
Coleta de dados das usinas Huawei FusionSolar (mesmo papel do coleta.py para a FoxESS).

Diferenças da Huawei (confirmadas no teste com a conta real):
- Tempo real por inversor NÃO traz o horário da leitura: usamos o momento da coleta.
- Energia diária vem por USINA (getKpiStationDay: todos os dias de um mês por chamada).
- Curva de 5 min vem por inversor (getDevHistoryKpi: até 10 inversores e 3 dias por chamada).
  Cota baixa: ~(nº de inversores / 10) + 24 chamadas por dia por tipo de inversor.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from monitoramento.models import Leitura
from monitoramento.particoes import criar_particoes
from usinas.models import Plataforma, Status, Usina

from .cadastro import status_da_usina
from .coleta import (
    Relatorio, _desde_a_primeira_geracao, _gravar_dias, desde_o_inicio, _meses_do_periodo, _numero, amostra_por_bloco,
    arredondar_5min, e_noite, leitura_recente, limite_curvas, sem_comunicacao,
)
from .huawei import HuaweiCliente, HuaweiErro, HuaweiLoginErro

ESTADOS_ONLINE = {512, 513, 514}      # conectado à rede (inclusive com limitação)
ESTADOS_FALHA = {768, 770}            # desligado por falha / por proteção da rede


def cliente_huawei() -> HuaweiCliente:
    return HuaweiCliente(settings.HUAWEI_API_URL, settings.HUAWEI_USUARIO, settings.HUAWEI_SENHA)


ESTADO_SEM_SOL = 40960               # standby: sem irradiância


def _status_inversor(dados: dict, noite: bool = False) -> str:
    try:
        estado = int(float(dados.get('inverter_state')))
    except (TypeError, ValueError):
        estado = None
    if estado in ESTADOS_FALHA:
        return Status.ALERTA                 # falha é alerta a qualquer hora
    if estado in ESTADOS_ONLINE or _numero(dados.get('active_power')) > 0:
        return Status.ONLINE
    if estado == ESTADO_SEM_SOL or noite:
        return Status.NOITE                  # sem sol: normal, não é problema
    return Status.OFFLINE                    # de dia e sem gerar: comunicação interrompida etc.


def _por_tipo(inversores) -> dict[int, list]:
    grupos = defaultdict(list)
    for inv in inversores:
        if inv.id_externo and inv.tipo_externo:
            grupos[int(inv.tipo_externo)].append(inv)
    return grupos


# ----------------------------------------------------------------------------
# Tempo real
# ----------------------------------------------------------------------------
def atualizar_tempo_real(usinas=None, api: HuaweiCliente | None = None) -> Relatorio:
    rel = Relatorio()
    qs = usinas if usinas is not None else Usina.objects.all()
    usinas = list(qs.ativas().filter(plataforma=Plataforma.HUAWEI).prefetch_related('inversores'))
    inversores = [inv for u in usinas for inv in u.inversores.all()]
    if not inversores:
        return rel
    api = api or cliente_huawei()

    dados: dict[str, dict] = {}
    for tipo, grupo in _por_tipo(inversores).items():
        try:
            for item in api.tempo_real_dispositivos([i.id_externo for i in grupo], tipo) or []:
                dados[str(item.get('devId'))] = item.get('dataItemMap') or {}
        except HuaweiLoginErro:
            raise
        except HuaweiErro as erro:   # um tipo de inversor com erro não derruba os outros
            rel.falhas.append(f'tipo {tipo}: {erro}')

    agora = timezone.now()   # a Huawei não informa o horário da leitura
    criar_particoes()
    for usina in usinas:
        lista = list(usina.inversores.all())
        with transaction.atomic():
            for inv in lista:
                d = dados.get(inv.id_externo)
                if d is None:
                    rel.falhas.append(f'{inv.numero_serie}: sem resposta no tempo real')
                if d is not None and _numero(d.get('run_state')) == 1:   # 1 = comunicando
                    inv.potencia_atual_kw = round(_numero(d.get('active_power')), 3)
                    inv.geracao_hoje_kwh = round(_numero(d.get('day_cap')), 3)
                    inv.status = _status_inversor(d, e_noite(agora, usina.fuso_horario))
                    inv.ultima_leitura = agora
                elif not leitura_recente(inv.ultima_leitura, usina, agora):
                    sem_comunicacao(inv, usina, agora)   # parou de comunicar há mais que o prazo
                inv.save(update_fields=['potencia_atual_kw', 'geracao_hoje_kwh', 'status', 'ultima_leitura'])
                rel.inversores += 1

            comunicando = [i for i in lista if i.ultima_leitura == agora]
            usina.status = status_da_usina([i.status for i in lista])
            if comunicando:
                usina.ultima_leitura = agora
                fuso = ZoneInfo(usina.fuso_horario)
                hoje = agora.astimezone(fuso).date()
                Leitura.objects.bulk_create(
                    [Leitura(usina=usina, data_hora=arredondar_5min(agora),
                             potencia_kw=round(sum(float(i.potencia_atual_kw) for i in lista), 3))],
                    update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
                )
                rel.leituras += 1
                _gravar_dias(usina, {hoje: sum(float(i.geracao_hoje_kwh) for i in lista if i.ultima_leitura
                                               and i.ultima_leitura.astimezone(fuso).date() == hoje)})
            usina.save(update_fields=['status', 'ultima_leitura', 'atualizado_em'])
    return rel


# ----------------------------------------------------------------------------
# Energia diária
# ----------------------------------------------------------------------------
def importar_geracao_diaria(usina: Usina, inicio: date, fim: date, api: HuaweiCliente | None = None) -> Relatorio:
    """1 chamada por mês: getKpiStationDay devolve todos os dias do mês (kWh)."""
    api = api or cliente_huawei()
    rel = Relatorio()
    fuso = ZoneInfo(usina.fuso_horario)
    inicio, fim = desde_o_inicio(usina, inicio), min(fim, timezone.localdate())
    por_dia: dict[date, float] = {}

    for ano, mes in _meses_do_periodo(inicio, fim):
        meio_do_mes = datetime(ano, mes, 15, 12, tzinfo=fuso)
        try:
            registros = api.kpi_diario([usina.id_externo], meio_do_mes)
        except HuaweiLoginErro:
            raise                      # sem login não adianta tentar os outros meses
        except HuaweiErro as erro:
            rel.falhas.append(f'{mes:02d}/{ano}: {erro}')
            continue
        for r in registros:
            dia = datetime.fromtimestamp(int(r.get('collectTime') or 0) / 1000, tz=fuso).date()
            m = r.get('dataItemMap') or {}
            valor = m.get('inverter_power') if m.get('inverter_power') is not None else m.get('PVYield')
            if inicio <= dia <= fim and valor is not None:
                por_dia[dia] = _numero(valor)

    por_dia = _desde_a_primeira_geracao(usina, por_dia)
    if por_dia:
        rel.dias = _gravar_dias(usina, por_dia)
    return rel


# ----------------------------------------------------------------------------
# Curva de 5 min
# ----------------------------------------------------------------------------
def importar_curvas(usina: Usina, inicio: date, fim: date, api: HuaweiCliente | None = None) -> Relatorio:
    """Janelas de 3 dias, até 10 inversores por chamada; soma os inversores por bloco de 5 min."""
    api = api or cliente_huawei()
    rel = Relatorio()
    fuso = ZoneInfo(usina.fuso_horario)
    inicio, fim = max(desde_o_inicio(usina, inicio), limite_curvas()), min(fim, timezone.localdate())
    criar_particoes(meses_antes=settings.LEITURAS_RETENCAO_MESES - 1)
    grupos = _por_tipo(usina.inversores.all())

    # Amostras de cada inversor (todas as janelas); só no fim escolhe uma por bloco e soma os inversores
    por_inversor: dict[str, list] = defaultdict(list)
    dias_com_falha: set[date] = set()
    janela = inicio
    while janela <= fim:
        ate = min(janela + timedelta(days=2), fim)
        comeco = datetime(janela.year, janela.month, janela.day, tzinfo=fuso)
        final = datetime(ate.year, ate.month, ate.day, tzinfo=fuso) + timedelta(days=1)
        for tipo, grupo in grupos.items():
            try:
                registros = api.historico_dispositivos([i.id_externo for i in grupo], tipo, comeco, final)
            except HuaweiLoginErro:
                raise
            except HuaweiErro as erro:
                dias_da_janela = {janela + timedelta(days=n) for n in range((ate - janela).days + 1)}
                if erro.codigo == 401:
                    rel.falhas.append('Curva de 5 min não liberada na conta Northbound: habilite os dados '
                                      'históricos dos inversores (String e Residencial) no portal FusionSolar.')
                    return _gravar_curva(usina, por_inversor, rel, dias_com_falha | dias_da_janela)
                rel.falhas.append(f'{janela:%d/%m}–{ate:%d/%m}: {erro}')
                dias_com_falha |= dias_da_janela
                if erro.e_limite:   # cota do dia acabou: grava o que veio
                    return _gravar_curva(usina, por_inversor, rel, dias_com_falha)
                continue
            for r in registros:
                momento = datetime.fromtimestamp(int(r.get('collectTime') or 0) / 1000, tz=fuso)
                por_inversor[str(r.get('devId'))].append(
                    (momento, _numero((r.get('dataItemMap') or {}).get('active_power'))))
        janela = ate + timedelta(days=1)
    return _gravar_curva(usina, por_inversor, rel, dias_com_falha)


def _gravar_curva(usina: Usina, por_inversor: dict[str, list], rel: Relatorio,
                  dias_com_falha: set[date] = frozenset()) -> Relatorio:
    """
    Uma amostra REAL por bloco para cada inversor (sem somar amostras do mesmo); depois soma os inversores.
    Dias em que algum grupo de inversores falhou não são gravados (a soma ficaria menor que a real).
    """
    fuso = ZoneInfo(usina.fuso_horario)
    soma: dict[datetime, float] = defaultdict(float)
    for pontos in por_inversor.values():
        for bloco, valor in amostra_por_bloco(pontos).items():
            if bloco.astimezone(fuso).date() not in dias_com_falha:
                soma[bloco] += valor
    # Dia todo zerado (a usina ainda não operava) não é gravado
    maximo_do_dia: dict[date, float] = defaultdict(float)
    for m, kw in soma.items():
        dia = m.astimezone(fuso).date()
        maximo_do_dia[dia] = max(maximo_do_dia[dia], kw)
    soma = {m: kw for m, kw in soma.items() if maximo_do_dia[m.astimezone(fuso).date()] > 0}
    if soma:
        Leitura.objects.bulk_create(
            [Leitura(usina=usina, data_hora=m, potencia_kw=round(kw, 3)) for m, kw in soma.items()],
            update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
        )
        rel.leituras = len(soma)
        rel.dias = len({m.astimezone(ZoneInfo(usina.fuso_horario)).date() for m in soma})
    return rel
