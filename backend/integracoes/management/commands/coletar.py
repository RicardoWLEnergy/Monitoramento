"""
Coleta automática: fica rodando e atualiza as usinas ativas.

Uso:
    python manage.py coletar                   (roda sem parar; Ctrl+C para encerrar)
    python manage.py coletar --uma-vez         (1 ciclo de tempo real + rotina diária e sai)
    python manage.py coletar --intervalo 5 --hora-diaria 1

- A cada `--intervalo` minutos (padrão 5): tempo real de todas as usinas.
- 1x por dia, a partir da `--hora-diaria` (padrão 1h da manhã) — e também ao iniciar:
  energia diária dos últimos dias, curva oficial de ontem e partições.
Só um coletor roda por vez (trava no banco).
"""
import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from integracoes.coletor import Clientes, Trava, ciclo_tempo_real, rotina_diaria

log = logging.getLogger('coletor')


class Command(BaseCommand):
    help = 'Coleta automática das usinas (tempo real a cada 5 min + rotina diária).'

    def add_arguments(self, parser):
        parser.add_argument('--intervalo', type=int, default=5, help='Minutos entre coletas de tempo real (padrão 5).')
        parser.add_argument('--hora-diaria', type=int, default=1, help='Hora da rotina diária (0-23, padrão 1).')
        parser.add_argument('--uma-vez', action='store_true', help='Roda um ciclo completo e sai.')

    def handle(self, *args, **opcoes):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%d/%m %H:%M:%S')
        trava = Trava()
        if not trava.obter():
            raise CommandError('Já existe um coletor rodando (trava ocupada no banco). Encerre-o antes de iniciar outro.')

        clientes = Clientes()
        ultima_rotina = None
        try:
            log.info('Coletor iniciado: tempo real a cada %s min, rotina diária às %sh.',
                     opcoes['intervalo'], opcoes['hora_diaria'])
            while True:
                inicio = time.monotonic()
                close_old_connections()   # evita conexão com o banco "velha" em execuções longas

                r = ciclo_tempo_real(clientes)
                log.info('Tempo real: %s inversor(es), %s leitura(s)%s', r.inversores, r.leituras,
                         f', {len(r.erros)} erro(s)' if r.erros else '')
                for erro in r.erros[:5]:
                    log.warning('  %s', erro)

                agora = timezone.localtime()
                if ultima_rotina != agora.date() and (ultima_rotina is None or agora.hour >= opcoes['hora_diaria']):
                    log.info('Rotina diária...')
                    r = rotina_diaria(clientes)
                    ultima_rotina = agora.date()
                    log.info('Rotina diária: %s dia(s) de energia, %s leitura(s) de curva%s', r.dias, r.leituras,
                             f', {len(r.erros)} erro(s)' if r.erros else '')
                    for erro in r.erros[:5]:
                        log.warning('  %s', erro)

                if opcoes['uma_vez']:
                    break
                espera = max(0, opcoes['intervalo'] * 60 - (time.monotonic() - inicio))
                time.sleep(espera)
        except KeyboardInterrupt:
            log.info('Coletor encerrado.')
        finally:
            trava.liberar()
