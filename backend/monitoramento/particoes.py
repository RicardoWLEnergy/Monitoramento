"""
Partições mensais da tabela monitoramento_leitura.

A tabela é dividida em "gavetas" por mês (monitoramento_leitura_2026_11, ...).
Para o Django e para as consultas ela continua sendo UMA tabela só.

- criar_particoes(): cria as gavetas do mês atual e dos próximos meses (rodar antes da coleta)
- remover_particoes_antigas(): descarta gavetas além do prazo de retenção (instantâneo)
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import connection

TABELA = 'monitoramento_leitura'


def _somar_meses(d: date, meses: int) -> date:
    total = d.year * 12 + (d.month - 1) + meses
    return date(total // 12, total % 12 + 1, 1)


def _inicio_do_mes(d: date) -> str:
    """Meia-noite do dia 1 no fuso do sistema (ex.: 2026-11-01T00:00:00-03:00)."""
    return datetime(d.year, d.month, 1, tzinfo=ZoneInfo(settings.TIME_ZONE)).isoformat()


def nome_particao(d: date) -> str:
    return f'{TABELA}_{d.year}_{d.month:02d}'


def particoes_existentes() -> list[str]:
    with connection.cursor() as c:
        c.execute(
            "SELECT child.relname FROM pg_inherits "
            "JOIN pg_class parent ON parent.oid = pg_inherits.inhparent "
            "JOIN pg_class child ON child.oid = pg_inherits.inhrelid "
            "WHERE parent.relname = %s ORDER BY child.relname",
            [TABELA],
        )
        return [linha[0] for linha in c.fetchall()]


def criar_particoes(meses_antes: int = 0, meses_depois: int = 3, hoje: date | None = None) -> list[str]:
    """Cria (se não existirem) as partições de [hoje - meses_antes, hoje + meses_depois]."""
    base = (hoje or date.today()).replace(day=1)
    criadas = []
    with connection.cursor() as c:
        for i in range(-meses_antes, meses_depois + 1):
            mes = _somar_meses(base, i)
            nome = nome_particao(mes)
            c.execute(
                f'CREATE TABLE IF NOT EXISTS "{nome}" PARTITION OF "{TABELA}" '
                f'FOR VALUES FROM (%s) TO (%s)',
                [_inicio_do_mes(mes), _inicio_do_mes(_somar_meses(mes, 1))],
            )
            criadas.append(nome)
    return criadas


def remover_particoes_antigas(retencao_meses: int | None = None, hoje: date | None = None) -> list[str]:
    """Descarta as partições anteriores ao prazo de retenção (mês atual + meses anteriores)."""
    retencao = retencao_meses or settings.LEITURAS_RETENCAO_MESES
    limite = nome_particao(_somar_meses((hoje or date.today()).replace(day=1), -(retencao - 1)))
    removidas = [p for p in particoes_existentes() if p < limite]
    with connection.cursor() as c:
        for nome in removidas:
            c.execute(f'DROP TABLE IF EXISTS "{nome}"')
    return removidas
