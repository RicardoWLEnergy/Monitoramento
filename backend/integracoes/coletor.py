"""
Coleta automática (usada pelo comando `python manage.py coletar`).

- ciclo_tempo_real(): a cada 5 min — status, potência, energia de hoje e um ponto da curva
  de todas as usinas ATIVAS (FoxESS e Huawei).
- rotina_diaria(): 1x por dia — energia diária dos últimos dias (corrige o dia anterior),
  curva oficial de ontem e manutenção das partições das leituras.

Cada plataforma roda isolada: erro em uma não interrompe a outra.
Os clientes das APIs são reaproveitados entre os ciclos (a Huawei limita logins).
"""
import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import DEFAULT_DB_ALIAS, connections
from django.utils import timezone

from monitoramento.particoes import criar_particoes, remover_particoes_antigas
from usinas.models import Plataforma, Usina

from . import coleta, coleta_huawei

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
