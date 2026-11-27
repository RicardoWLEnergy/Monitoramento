"""
Coleta de dados das usinas Sungrow iSolarCloud (mesmo papel do coleta.py para a FoxESS).

- Tempo real: por inversor (lotes de até 50 do mesmo tipo), com o horário da leitura.
- Energia diária: por USINA (ps_key "{ps_id}_11_0_0", ponto 83022, até 100 dias por chamada).
  O histórico da Sungrow não traz o dia de hoje: hoje vem do tempo real.
- Curva de 5 min: por USINA (ponto 83033), em janelas de 3 h — só das 5h às 20h (5 chamadas por dia).
Unidades: a Sungrow manda na menor unidade (W, Wh); tudo é convertido para kW e kWh.
"""
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from monitoramento.models import Leitura
from monitoramento.particoes import criar_particoes
from usinas.models import Plataforma, Status, Usina

from .coleta import (
    Relatorio, _desde_a_primeira_geracao, _gravar_dias, _numero, amostra_por_bloco, desde_o_inicio,
    fechar_tempo_real, leitura_recente, limite_curvas, pouco_sol, sem_comunicacao,
)
from .sungrow import (
    TIPO_HIBRIDO, TIPO_INVERSOR, SungrowCliente, SungrowErro, SungrowLimiteErro, SungrowLoginErro, ps_key_da_usina,
)

# Pontos por tipo de inversor: (potência, energia do dia, estado)
PONTOS = {
    TIPO_INVERSOR: ('24', '1', '29'),
    TIPO_HIBRIDO: ('13011', '13112', '13146'),
}
PONTO_ENERGIA_USINA = '83022'    # geração diária da usina (Wh)
PONTO_POTENCIA_USINA = '83033'   # potência da usina (W)

# Estado de operação do inversor (ponto 29): 0 conectado à rede · 64 operando normalmente ·
# 5120/8 standby · 32768/1 desligado · 21760 desligado por falha · 37120 operando com alarme ·
# 33024/128 operando com redução de potência · 256 falha de operação.
# (O estado do híbrido, ponto 13146, tem outra tabela: vale só a falha informada e a potência.)
ESTADOS_ONLINE = {0, 64, 37120, 33024, 128}
ESTADOS_FALHA = {21760, 256}
COM_FALHA = 1                    # dev_fault_status: 1 falha · 2 alarme · 4 normal

# Janelas da curva (horário da usina): a Sungrow aceita até 3 h por chamada
JANELAS_CURVA = ((5, 8), (8, 11), (11, 14), (14, 17), (17, 20))

SEM_VALOR = (None, '', '--')

# "GMT-3" → fuso do Brasil (sem horário de verão); outros → Etc/GMT
FUSOS_GMT = {-2: 'America/Noronha', -3: 'America/Sao_Paulo', -4: 'America/Manaus', -5: 'America/Rio_Branco'}


def cliente_sungrow() -> SungrowCliente:
    return SungrowCliente()


def em_k(valor) -> float:
    """Valor da Sungrow (W ou Wh) → kW ou kWh."""
    return _numero(valor) / 1000


def fuso_sungrow(texto: str | None) -> str:
    """'GMT-3' -> America/Sao_Paulo · 'GMT+1' -> Etc/GMT-1 · desconhecido -> America/Sao_Paulo."""
    achado = re.fullmatch(r'(?:GMT|UTC)\s*([+-])\s*(\d{1,2})(?::?00)?', (texto or '').strip(), re.IGNORECASE)
    if not achado:
        return 'America/Sao_Paulo'
    horas = int(achado[2]) * (-1 if achado[1] == '-' else 1)
    return FUSOS_GMT.get(horas) or (f'Etc/GMT{-horas:+d}' if horas else 'UTC')


def momento_sungrow(texto, fuso: str) -> datetime | None:
    """'20241127151500' (fuso da usina) -> datetime."""
    try:
        return datetime.strptime(str(texto or '')[:14], '%Y%m%d%H%M%S').replace(tzinfo=ZoneInfo(fuso))
    except ValueError:
        return None


def _status_inversor(dados: dict, tipo: int, potencia: float, pouco_sol: bool = False) -> str:
    """Mesma regra das outras plataformas (inversor comunicando): falha → alerta; sem gerar em pleno dia → alerta."""
    try:
        estado = int(float(dados.get(f'p{PONTOS[tipo][2]}'))) if tipo == TIPO_INVERSOR else None
    except (TypeError, ValueError):
        estado = None
    if _numero(dados.get('dev_fault_status')) == COM_FALHA or estado in ESTADOS_FALHA:
        return Status.ALERTA
    if estado in ESTADOS_ONLINE or potencia > 0:
        return Status.ONLINE
    return Status.NOITE if pouco_sol else Status.ALERTA


def _por_tipo(inversores) -> dict[int, list]:
    grupos = defaultdict(list)
    for inv in inversores:
        if inv.id_externo and inv.tipo_externo and int(inv.tipo_externo) in PONTOS:
            grupos[int(inv.tipo_externo)].append(inv)
    return grupos


# ----------------------------------------------------------------------------
# Tempo real
# ----------------------------------------------------------------------------
def atualizar_tempo_real(usinas=None, api: SungrowCliente | None = None) -> Relatorio:
    rel = Relatorio()
    qs = usinas if usinas is not None else Usina.objects.all()
    usinas = list(qs.ativas().filter(plataforma=Plataforma.SUNGROW).prefetch_related('inversores'))
    inversores = [inv for u in usinas for inv in u.inversores.all()]
    if not inversores:
        return rel
    api = api or cliente_sungrow()

    dados: dict[str, tuple[dict, int]] = {}   # ps_key -> (leitura, tipo)
    for tipo, grupo in _por_tipo(inversores).items():
        try:
            itens = api.tempo_real_dispositivos(tipo, list(PONTOS[tipo]), ps_keys=[i.id_externo for i in grupo])
        except (SungrowLoginErro, SungrowLimiteErro):
            raise                       # sem acesso ou sem cota: nada mais vai funcionar neste ciclo
        except SungrowErro as erro:     # um tipo de inversor com erro não derruba os outros
            rel.falhas.append(f'tipo {tipo}: {erro}')
            continue
        for item in itens:
            dados[str(item.get('ps_key'))] = (item, tipo)

    agora = timezone.now()
    criar_particoes()
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
        achado = dados.get(inv.id_externo)
        if not achado:
            rel.falhas.append(f'{inv.numero_serie}: sem resposta no tempo real')
        item, tipo = achado or ({}, None)
        momento = momento_sungrow(item.get('device_time'), usina.fuso_horario) if achado else None
        if achado and leitura_recente(momento, usina, agora):
            ponto_potencia, ponto_energia, _ = PONTOS[tipo]
            potencia = max(em_k(item.get(f'p{ponto_potencia}')), 0.0)
            inv.potencia_atual_kw = round(potencia, 3)
            inv.geracao_hoje_kwh = round(em_k(item.get(f'p{ponto_energia}')), 3)
            inv.status = _status_inversor(item, tipo, potencia, pouco_sol(momento, usina.fuso_horario))
            inv.ultima_leitura = momento
        else:
            sem_comunicacao(inv, usina, agora)
        inv.save(update_fields=['potencia_atual_kw', 'geracao_hoje_kwh', 'status', 'ultima_leitura'])
        rel.inversores += 1
    fechar_tempo_real(usina, lista, agora, rel)


# ----------------------------------------------------------------------------
# Energia diária
# ----------------------------------------------------------------------------
def importar_geracao_diaria(usina: Usina, inicio: date, fim: date, api: SungrowCliente | None = None) -> Relatorio:
    """Energia de cada dia (ponto 83022 da usina), até 100 dias por chamada. Hoje fica com o tempo real."""
    api = api or cliente_sungrow()
    rel = Relatorio()
    inicio = desde_o_inicio(usina, inicio)
    fim = min(fim, timezone.localdate() - timedelta(days=1))
    chave = ps_key_da_usina(usina.id_externo)
    por_dia: dict[date, float] = {}
    de = inicio
    while de <= fim:
        ate = min(de + timedelta(days=99), fim)
        try:
            dados = api.historico_diario([chave], PONTO_ENERGIA_USINA, de, ate)
        except (SungrowLoginErro, SungrowLimiteErro):
            raise
        except SungrowErro as erro:
            rel.falhas.append(f'{de:%d/%m/%Y}–{ate:%d/%m/%Y}: {erro}')
            de = ate + timedelta(days=1)
            continue
        for r in (dados.get(chave) or {}).get(f'p{PONTO_ENERGIA_USINA}') or []:
            try:
                dia = datetime.strptime(str(r.get('time_stamp') or '')[:8], '%Y%m%d').date()
            except ValueError:
                continue
            if r.get('2') not in SEM_VALOR and de <= dia <= ate:
                por_dia[dia] = em_k(r.get('2'))
        de = ate + timedelta(days=1)

    por_dia = _desde_a_primeira_geracao(usina, por_dia)
    if por_dia:
        rel.dias = _gravar_dias(usina, por_dia)
    return rel


# ----------------------------------------------------------------------------
# Curva de 5 min
# ----------------------------------------------------------------------------
def importar_curvas(usina: Usina, inicio: date, fim: date, api: SungrowCliente | None = None) -> Relatorio:
    """Potência da usina a cada 5 min (ponto 83033), 5 janelas de 3 h por dia. Hoje fica com o tempo real."""
    api = api or cliente_sungrow()
    rel = Relatorio()
    fuso = ZoneInfo(usina.fuso_horario)
    inicio = max(desde_o_inicio(usina, inicio), limite_curvas())
    fim = min(fim, timezone.localdate() - timedelta(days=1))
    criar_particoes(meses_antes=settings.LEITURAS_RETENCAO_MESES - 1)
    chave = ps_key_da_usina(usina.id_externo)

    dia = fim
    while dia >= inicio:
        pontos: list[tuple[datetime, float]] = []
        for hora_de, hora_ate in JANELAS_CURVA:
            comeco = datetime(dia.year, dia.month, dia.day, hora_de, tzinfo=fuso)
            final = datetime(dia.year, dia.month, dia.day, hora_ate, tzinfo=fuso)
            try:
                dados = api.historico_minuto([chave], PONTO_POTENCIA_USINA, comeco, final)
            except (SungrowLoginErro, SungrowLimiteErro):
                raise                   # os dias anteriores já ficaram gravados
            except SungrowErro as erro:
                rel.falhas.append(f'{dia:%d/%m} {hora_de}h–{hora_ate}h: {erro}')
                continue
            for r in dados.get(chave) or []:
                momento = momento_sungrow(r.get('time_stamp'), usina.fuso_horario)
                valor = r.get(f'p{PONTO_POTENCIA_USINA}')
                if momento and valor not in SEM_VALOR:
                    pontos.append((momento, max(em_k(valor), 0.0)))
        blocos = amostra_por_bloco(pontos)
        # Dia todo zerado (a usina ainda não operava) não é gravado
        if blocos and max(blocos.values()) > 0:
            Leitura.objects.bulk_create(
                [Leitura(usina=usina, data_hora=m, potencia_kw=round(kw, 3)) for m, kw in blocos.items()],
                update_conflicts=True, unique_fields=['usina', 'data_hora'], update_fields=['potencia_kw'],
            )
            rel.leituras += len(blocos)
            rel.dias += 1
        dia -= timedelta(days=1)
    return rel
