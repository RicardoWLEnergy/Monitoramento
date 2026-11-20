"""
Coleta automática: fica rodando e atualiza as usinas ativas.

Uso:
    python manage.py coletar                   (roda sem parar; Ctrl+C para encerrar)
    python manage.py coletar --uma-vez         (1 ciclo de tempo real + rotina diária e sai)
    python manage.py coletar --intervalo 5 --hora-diaria 1

- A cada `--intervalo` minutos (padrão 5): tempo real de todas as usinas.
- 1x por dia, a partir da `--hora-diaria` (padrão 1h da manhã) — e também ao iniciar:
  energia diária dos últimos dias, curva oficial de ontem e partições.
- No tempo livre entre os ciclos: importações de histórico pedidas na tela, em pedaços curtos.
  O tempo real tem prioridade: a importação pausa quando chega a hora do próximo ciclo.
Só um coletor roda por vez (trava no banco).
"""
import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from django.utils import timezone

from integracoes.coletor import (
    Clientes, Trava, atualizar_clima_recente, ciclo_tempo_real, processar_fila, rotina_diaria,
)

log = logging.getLogger('coletor')

ESPERA_FILA = 10   # segundos entre olhadas na fila de importações quando não há nada a fazer
FOLGA = 5          # segundos antes do próximo ciclo em que não se começa outro pedaço de importação


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
                proximo_ciclo = inicio + opcoes['intervalo'] * 60
                try:
                    close_old_connections()   # evita conexão com o banco "velha" em execuções longas
                    ultima_rotina = self.ciclo(clientes, opcoes, ultima_rotina)
                except Exception:   # noqa: BLE001 — banco fora do ar etc.: registra e tenta no próximo ciclo
                    log.exception('Ciclo do coletor falhou; tenta de novo no próximo.')

                if opcoes['uma_vez']:
                    break
                self.tempo_livre(clientes, proximo_ciclo)
        except KeyboardInterrupt:
            log.info('Coletor encerrado.')
        finally:
            trava.liberar()

    @staticmethod
    def ciclo(clientes: Clientes, opcoes: dict, ultima_rotina):
        """Tempo real (sempre) + rotina diária (1x por dia). Devolve o dia da última rotina."""
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
        return ultima_rotina

    @staticmethod
    def tempo_livre(clientes: Clientes, proximo_ciclo: float) -> None:
        """Até o próximo ciclo de tempo real: importações da fila; sem nada na fila, olha de novo a cada 10 s."""
        # Clima (secundário): só se sobrar folga antes do próximo ciclo, com prazo que termina antes dele
        folga = proximo_ciclo - time.monotonic() - FOLGA
        if folga > 30:
            atualizar_clima_recente(segundos=min(60, folga - 10))
        while time.monotonic() < proximo_ciclo:
            close_old_connections()
            try:
                feitos = processar_fila(clientes, prazo=proximo_ciclo - FOLGA)
            except Exception:   # noqa: BLE001 — problema na fila nunca pode parar o tempo real
                log.exception('Fila de importações falhou')
                feitos = 0
            if not feitos:
                time.sleep(max(0, min(ESPERA_FILA, proximo_ciclo - time.monotonic())))
