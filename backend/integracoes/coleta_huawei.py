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
from .coleta import Relatorio, _gravar_dias, _meses_do_periodo, _numero, arredondar_5min, e_noite, limite_curvas
from .huawei import HuaweiCliente, HuaweiErro

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
    fusos = {inv.numero_serie: u.fuso_horario for u in usinas for inv in u.inversores.all()}
    if not inversores:
        return rel
    api = api or cliente_huawei()

    dados: dict[str, dict] = {}
    for tipo, grupo in _por_tipo(inversores).items():
        for item in api.tempo_real_dispositivos([i.id_externo for i in grupo], tipo):
            dados[str(item.get('devId'))] = item.get('dataItemMap') or {}

    agora = timezone.now()   # a Huawei não informa o horário da leitura
    criar_particoes()
    with transaction.atomic():
        for inv in inversores:
            d = dados.get(inv.id_externo)
            if d is None:
                rel.falhas.append(f'{inv.numero_serie}: sem resposta no tempo real')
                continue
            inv.potencia_atual_kw = round(_numero(d.get('active_power')), 3)   # kW (a confirmar de dia)
            inv.geracao_hoje_kwh = round(_numero(d.get('day_cap')), 3)
            inv.status = _status_inversor(d, e_noite(agora, fusos[inv.numero_serie]))
            if _numero(d.get('run_state')) == 1:   # 1 = comunicando
                inv.ultima_leitura = agora
            inv.save(update_fields=['potencia_atual_kw', 'geracao_hoje_kwh', 'status', 'ultima_leitura'])
            rel.inversores += 1

        for usina in usinas:
            lista = list(usina.inversores.all())
            comunicando = [i for i in lista if i.ultima_leitura == agora]
            usina.status = status_da_usina([i.status for i in lista])
            if comunicando:
                usina.ultima_leitura = agora
                Leitura.objects.bulk_create(
                    [Leitura(usina=usina, data_hora=arredondar_5min(agora),
                             potencia_kw=round(sum(float(i.potencia_atual_kw) for i in lista), 3))],
                    update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
                )
                rel.leituras += 1
                hoje = agora.astimezone(ZoneInfo(usina.fuso_horario)).date()
                _gravar_dias(usina, {hoje: sum(float(i.geracao_hoje_kwh) for i in lista)})
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
    fim = min(fim, timezone.localdate())
    por_dia: dict[date, float] = {}

    for ano, mes in _meses_do_periodo(inicio, fim):
        meio_do_mes = datetime(ano, mes, 15, 12, tzinfo=fuso)
        try:
            registros = api.kpi_diario([usina.id_externo], meio_do_mes)
        except HuaweiErro as erro:
            rel.falhas.append(f'{mes:02d}/{ano}: {erro}')
            continue
        for r in registros:
            dia = datetime.fromtimestamp(int(r.get('collectTime') or 0) / 1000, tz=fuso).date()
            m = r.get('dataItemMap') or {}
            valor = m.get('inverter_power') if m.get('inverter_power') is not None else m.get('PVYield')
            if inicio <= dia <= fim and valor is not None:
                por_dia[dia] = _numero(valor)

    com_geracao = sorted(d for d, kwh in por_dia.items() if kwh > 0)
    if com_geracao:
        rel.dias = _gravar_dias(usina, {d: kwh for d, kwh in por_dia.items() if d >= com_geracao[0]})
    return rel


# ----------------------------------------------------------------------------
# Curva de 5 min
# ----------------------------------------------------------------------------
def importar_curvas(usina: Usina, inicio: date, fim: date, api: HuaweiCliente | None = None) -> Relatorio:
    """Janelas de 3 dias, até 10 inversores por chamada; soma os inversores por bloco de 5 min."""
    api = api or cliente_huawei()
    rel = Relatorio()
    fuso = ZoneInfo(usina.fuso_horario)
    inicio, fim = max(inicio, limite_curvas()), min(fim, timezone.localdate())
    criar_particoes(meses_antes=settings.LEITURAS_RETENCAO_MESES - 1)
    grupos = _por_tipo(usina.inversores.all())

    soma: dict[datetime, float] = defaultdict(float)
    janela = inicio
    while janela <= fim:
        ate = min(janela + timedelta(days=2), fim)
        comeco = datetime(janela.year, janela.month, janela.day, tzinfo=fuso)
        final = datetime(ate.year, ate.month, ate.day, tzinfo=fuso) + timedelta(days=1)
        for tipo, grupo in grupos.items():
            try:
                registros = api.historico_dispositivos([i.id_externo for i in grupo], tipo, comeco, final)
            except HuaweiErro as erro:
                if erro.codigo == 401:
                    rel.falhas.append('Curva de 5 min não liberada na conta Northbound: habilite os dados '
                                      'históricos dos inversores (String e Residencial) no portal FusionSolar.')
                    return _gravar_curva(usina, soma, rel)
                rel.falhas.append(f'{janela:%d/%m}–{ate:%d/%m}: {erro}')
                if erro.e_limite:
                    return _gravar_curva(usina, soma, rel)   # cota do dia acabou: grava o que veio
                continue
            for r in registros:
                momento = datetime.fromtimestamp(int(r.get('collectTime') or 0) / 1000, tz=fuso)
                soma[arredondar_5min(momento)] += _numero((r.get('dataItemMap') or {}).get('active_power'))
        janela = ate + timedelta(days=1)
    return _gravar_curva(usina, soma, rel)


def _gravar_curva(usina: Usina, soma: dict[datetime, float], rel: Relatorio) -> Relatorio:
    if soma:
        Leitura.objects.bulk_create(
            [Leitura(usina=usina, data_hora=m, potencia_kw=round(kw, 3)) for m, kw in soma.items()],
            update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
        )
        rel.leituras = len(soma)
        rel.dias = len({m.astimezone(ZoneInfo(usina.fuso_horario)).date() for m in soma})
    return rel
