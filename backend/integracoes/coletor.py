"""
Coleta automática (usada pelo comando `python manage.py coletar`).

- ciclo_tempo_real(): a cada 5 min — status, potência, energia de hoje e um ponto da curva
  de todas as usinas ATIVAS (FoxESS e Huawei).
- rotina_diaria(): 1x por dia — energia diária dos últimos dias (corrige o dia anterior),
  curva oficial de ontem e manutenção das partições das leituras.
- processar_fila(): importações de histórico pedidas na tela, em pedaços, só no tempo livre
  entre os ciclos de tempo real (o tempo real tem prioridade).

Cada plataforma roda isolada: erro em uma não interrompe a outra.
Os clientes das APIs são reaproveitados entre os ciclos (a Huawei limita logins).
"""
import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

import requests
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.models import Q
from django.utils import timezone

from monitoramento.models import ImportacaoHistorico
from monitoramento.particoes import criar_particoes, remover_particoes_antigas
from usinas.models import Plataforma, Usina

from . import clima, coleta, coleta_huawei
from .huawei import HuaweiLoginErro

log = logging.getLogger('coletor')

# Número arbitrário que identifica a trava do coletor no PostgreSQL
ID_TRAVA = 760_2026


@dataclass
class Clientes:
    """Conexões com as APIs, criadas sob demanda e reaproveitadas."""
    _foxess: object = None
    _huawei: object = None
    curva_huawei_bloqueada: bool = False   # 401: interface não liberada na conta Northbound

    def foxess(self):
        if self._foxess is None:
            self._foxess = coleta.cliente_foxess()
        return self._foxess

    def huawei(self):
        if self._huawei is None:
            self._huawei = coleta_huawei.cliente_huawei()
        return self._huawei


@dataclass
class Resumo:
    inversores: int = 0
    leituras: int = 0
    dias: int = 0
    erros: list[str] = field(default_factory=list)


def _tem_usinas(plataforma: str) -> bool:
    return Usina.objects.ativas().filter(plataforma=plataforma).exists()


def ciclo_tempo_real(clientes: Clientes) -> Resumo:
    resumo = Resumo()
    tarefas = [
        (Plataforma.FOXESS, lambda: coleta.atualizar_tempo_real(api=clientes.foxess())),
        (Plataforma.HUAWEI, lambda: coleta_huawei.atualizar_tempo_real(api=clientes.huawei())),
    ]
    for plataforma, tarefa in tarefas:
        if not _tem_usinas(plataforma):
            continue
        try:
            r = tarefa()
            resumo.inversores += r.inversores
            resumo.leituras += r.leituras
            resumo.erros += [f'{plataforma}: {f}' for f in r.falhas]
        except Exception as erro:   # noqa: BLE001 — o coletor nunca pode parar por causa de uma plataforma
            log.exception('Tempo real %s falhou', plataforma)
            resumo.erros.append(f'{plataforma}: {erro}')
    return resumo


INTERVALO_CLIMA = 3 * 60 * 60   # segundos entre atualizações do clima de hoje
_ultimo_clima = {'quando': None}


def atualizar_clima_recente(segundos: float = 60, forcar: bool = False) -> None:
    """
    Clima de ontem e de hoje das usinas ativas, no máximo a cada 3 h e só no TEMPO LIVRE do coletor,
    com prazo de `segundos`. É informação secundária: qualquer erro só vai para o log.
    """
    agora = time.monotonic()
    if not forcar and _ultimo_clima['quando'] is not None and agora - _ultimo_clima['quando'] < INTERVALO_CLIMA:
        return
    _ultimo_clima['quando'] = agora
    hoje = timezone.localdate()
    try:
        dias = clima.atualizar_clima(Usina.objects.ativas(), hoje - timedelta(days=1), hoje, segundos=segundos)
        log.info('Clima: %s registro(s) atualizado(s).', dias)
    except clima.ClimaErro as erro:
        log.warning('Clima indisponível: %s', erro)
    except Exception:   # noqa: BLE001 — o clima nunca pode atrapalhar a coleta
        log.exception('Clima falhou')


def rotina_diaria(clientes: Clientes, dias_energia: int = 3) -> Resumo:
    """Energia diária dos últimos `dias_energia` dias + curva oficial de ontem + partições."""
    resumo = Resumo()
    hoje = timezone.localdate()
    ontem = hoje - timedelta(days=1)

    try:
        criar_particoes(meses_depois=3)
        removidas = remover_particoes_antigas()
        if removidas:
            log.info('Partições removidas (fora da retenção): %s', ', '.join(removidas))
    except Exception as erro:   # noqa: BLE001
        log.exception('Manutenção de partições falhou')
        resumo.erros.append(f'partições: {erro}')

    for usina in Usina.objects.ativas().prefetch_related('inversores'):
        try:
            if usina.plataforma == Plataforma.FOXESS:
                api, modulo = clientes.foxess(), coleta
            elif usina.plataforma == Plataforma.HUAWEI:
                api, modulo = clientes.huawei(), coleta_huawei
            else:
                continue

            r = modulo.importar_geracao_diaria(usina, hoje - timedelta(days=dias_energia - 1), hoje, api=api)
            resumo.dias += r.dias
            resumo.erros += [f'{usina.nome}: {f}' for f in r.falhas]

            if usina.plataforma == Plataforma.HUAWEI and clientes.curva_huawei_bloqueada:
                continue   # não insiste numa interface que a conta não liberou
            r = modulo.importar_curvas(usina, ontem, ontem, api=api)
            resumo.leituras += r.leituras
            if any('não liberada' in f for f in r.falhas):
                clientes.curva_huawei_bloqueada = True
                log.warning('Curva de 5 min da Huawei não liberada na conta Northbound; '
                            'o histórico de ontem fica só com as leituras do tempo real.')
            else:
                resumo.erros += [f'{usina.nome}: {f}' for f in r.falhas]
        except Exception as erro:   # noqa: BLE001
            log.exception('Rotina diária falhou para %s', usina.nome)
            resumo.erros.append(f'{usina.nome}: {erro}')
    return resumo


# ----------------------------------------------------------------------------
# Fila de importações de histórico (pedidas pela tela)
# ----------------------------------------------------------------------------
# Tamanho do pedaço de curva: FoxESS busca 1 dia por chamada; Huawei, até 3 dias por chamada
DIAS_POR_PASSO_CURVA = {Plataforma.FOXESS: 1, Plataforma.HUAWEI: 3}
# Erros passageiros: a importação pausa e tenta de novo depois (não avança o cursor)
ERROS_PASSAGEIROS = (requests.RequestException, HuaweiLoginErro)
PAUSA_APOS_ERRO = timedelta(minutes=10)
AVISO_CURVA_HUAWEI = ('Curva de 5 min não liberada na conta Northbound; '
                      'a curva destes dias fica só com as leituras do tempo real.')
Imp = ImportacaoHistorico


def processar_fila(clientes: Clientes, prazo: float, relogio=time.monotonic) -> int:
    """
    Executa pedaços das importações pendentes (a mais antiga primeiro) até o `prazo`
    (valor de time.monotonic() do próximo ciclo de tempo real). Devolve quantos pedaços fez.
    Cada pedaço é curto (1 mês de energia ou 1 dia de curva), então o tempo real nunca espera muito.
    """
    feitos = 0
    while relogio() < prazo:
        imp = (Imp.objects.filter(status__in=Imp.ATIVOS)
               .filter(Q(tentar_apos__isnull=True) | Q(tentar_apos__lte=timezone.now()))
               .select_related('usina').order_by('criado_em').first())
        if imp is None:
            break
        executar_passo(imp, clientes)
        feitos += 1
    return feitos


def _periodo_curva(imp: ImportacaoHistorico) -> tuple[date, date] | None:
    if not imp.curvas:
        return None
    inicio, fim = max(imp.inicio, coleta.limite_curvas()), min(imp.fim, timezone.localdate())
    return (inicio, fim) if inicio <= fim else None


def _passos_curva(imp: ImportacaoHistorico) -> int:
    periodo = _periodo_curva(imp)
    if periodo is None:
        return 0
    tamanho = DIAS_POR_PASSO_CURVA[imp.usina.plataforma]
    return -(-((periodo[1] - periodo[0]).days + 1) // tamanho)   # divisão arredondando para cima


def _iniciar(imp: ImportacaoHistorico) -> None:
    imp.status, imp.iniciado_em = Imp.Status.IMPORTANDO, timezone.now()
    imp.etapa, imp.cursor = Imp.Etapa.ENERGIA, min(imp.fim, timezone.localdate())
    imp.passos_feitos = 0
    imp.passos_total = len(coleta._meses_do_periodo(imp.inicio, imp.cursor)) + _passos_curva(imp)
    log.info('Importação de histórico iniciada: %s (%s a %s).', imp.usina.nome,
             f'{imp.inicio:%d/%m/%Y}', f'{imp.fim:%d/%m/%Y}')
    try:   # o clima do período vem junto (rápido e sem atrapalhar a importação)
        clima.atualizar_clima([imp.usina], imp.inicio, imp.fim, segundos=20)
    except clima.ClimaErro as erro:
        log.warning('Clima do período indisponível (%s): %s', imp.usina.nome, erro)
    except Exception:   # noqa: BLE001
        log.exception('Clima do período falhou (%s)', imp.usina.nome)


def _ir_para_curva_ou_concluir(imp: ImportacaoHistorico, clientes: Clientes) -> None:
    periodo = _periodo_curva(imp)
    if imp.etapa == Imp.Etapa.ENERGIA and periodo:
        if imp.usina.plataforma == Plataforma.HUAWEI and clientes.curva_huawei_bloqueada:
            imp.anotar_falhas([AVISO_CURVA_HUAWEI])
        else:
            imp.etapa, imp.cursor = Imp.Etapa.CURVA, periodo[1]
            return
    imp.status, imp.concluido_em, imp.cursor = Imp.Status.CONCLUIDA, timezone.now(), None
    imp.passos_feitos = imp.passos_total
    log.info('Importação de histórico concluída: %s (%s dia(s) de energia, %s de curva).',
             imp.usina.nome, imp.dias_energia, imp.dias_curva)


def executar_passo(imp: ImportacaoHistorico, clientes: Clientes) -> None:
    """Um pedaço da importação: 1 mês de energia diária ou 1 dia (FoxESS) / 3 dias (Huawei) de curva."""
    usina = imp.usina
    try:
        if not usina.ativa:
            raise ValueError('A usina foi apagada.')
        if usina.plataforma == Plataforma.FOXESS:
            api, modulo = clientes.foxess(), coleta
        elif usina.plataforma == Plataforma.HUAWEI:
            api, modulo = clientes.huawei(), coleta_huawei
        else:
            raise ValueError('Esta plataforma não tem importação de histórico.')

        if imp.status == Imp.Status.FILA:
            _iniciar(imp)

        if imp.etapa == Imp.Etapa.ENERGIA:
            ate = imp.cursor
            de = max(imp.inicio, ate.replace(day=1))                    # 1 mês por vez, do mais recente ao mais antigo
            r = modulo.importar_geracao_diaria(usina, de, ate, api=api)
            imp.dias_energia += r.dias
            imp.anotar_falhas(r.falhas)
            imp.cursor = de - timedelta(days=1)
            imp.passos_feitos += 1
            if imp.cursor < imp.inicio:
                _ir_para_curva_ou_concluir(imp, clientes)
        else:
            periodo = _periodo_curva(imp)
            if periodo is None or imp.cursor is None:   # período saiu da retenção: nada mais a importar
                _ir_para_curva_ou_concluir(imp, clientes)
                imp.save()
                return
            inicio_curva = periodo[0]
            ate = imp.cursor
            de = max(inicio_curva, ate - timedelta(days=DIAS_POR_PASSO_CURVA[usina.plataforma] - 1))
            r = modulo.importar_curvas(usina, de, ate, api=api)
            imp.dias_curva += r.dias
            imp.leituras += r.leituras
            imp.cursor = de - timedelta(days=1)
            imp.passos_feitos += 1
            if any('não liberada' in f for f in r.falhas):
                clientes.curva_huawei_bloqueada = True                  # não insiste nos dias restantes
                imp.anotar_falhas([AVISO_CURVA_HUAWEI])
                imp.cursor = inicio_curva - timedelta(days=1)
            else:
                imp.anotar_falhas(r.falhas)
            if imp.cursor < inicio_curva:
                _ir_para_curva_ou_concluir(imp, clientes)
    except ERROS_PASSAGEIROS as erro:
        imp.erros_temporarios += 1
        if imp.erros_temporarios >= Imp.MAX_ERROS_TEMPORARIOS:
            log.error('Importação de histórico desistiu após %s erros seguidos: %s', imp.erros_temporarios, usina.nome)
            imp.anotar_falhas([f'Plataforma indisponível: {erro}'])
            imp.status, imp.concluido_em = Imp.Status.ERRO, timezone.now()
        else:
            log.warning('Importação de histórico pausada (%s): %s — tenta de novo em 10 min.', usina.nome, erro)
            imp.tentar_apos = timezone.now() + PAUSA_APOS_ERRO
    except Exception as erro:   # noqa: BLE001 — erro inesperado encerra só esta importação, nunca o coletor
        log.exception('Importação de histórico falhou: %s', usina.nome)
        imp.anotar_falhas([str(erro)])
        imp.status, imp.concluido_em = Imp.Status.ERRO, timezone.now()
    else:
        imp.erros_temporarios, imp.tentar_apos = 0, None
    imp.save()


# ----------------------------------------------------------------------------
# Trava: impede dois coletores ao mesmo tempo (dobraria as chamadas às APIs)
# ----------------------------------------------------------------------------
class Trava:
    """
    Trava do PostgreSQL (advisory lock), que vale enquanto a CONEXÃO estiver aberta.
    Usa uma conexão exclusiva: o coletor fecha/reabre as conexões normais a cada ciclo
    (close_old_connections), o que soltaria a trava se ela usasse a conexão padrão.
    """

    def __init__(self):
        self._conexao = connections.create_connection(DEFAULT_DB_ALIAS)

    def obter(self) -> bool:
        with self._conexao.cursor() as c:
            c.execute('SELECT pg_try_advisory_lock(%s)', [ID_TRAVA])
            obtida = bool(c.fetchone()[0])
        if not obtida:
            self._conexao.close()
        return obtida

    def liberar(self) -> None:
        self._conexao.close()   # fechar a conexão solta a trava
