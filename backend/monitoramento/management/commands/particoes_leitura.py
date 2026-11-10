from django.conf import settings
from django.core.management.base import BaseCommand

from monitoramento.particoes import criar_particoes, particoes_existentes, remover_particoes_antigas


class Command(BaseCommand):
    help = (
        'Mantém as partições mensais da tabela de leituras: cria as dos próximos meses '
        'e remove as que passaram do prazo de retenção (LEITURAS_RETENCAO_MESES).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--meses-a-frente', type=int, default=3,
                            help='Quantos meses futuros deixar prontos (padrão: 3).')
        parser.add_argument('--sem-remover', action='store_true',
                            help='Só cria; não remove partições antigas.')

    def handle(self, *args, **opcoes):
        criar_particoes(meses_depois=opcoes['meses_a_frente'])
        removidas = [] if opcoes['sem_remover'] else remover_particoes_antigas()

        existentes = particoes_existentes()
        self.stdout.write(f'Retenção: {settings.LEITURAS_RETENCAO_MESES} meses')
        self.stdout.write(f'Partições: {len(existentes)} ({existentes[0]} até {existentes[-1]})' if existentes else 'Partições: nenhuma')
        if removidas:
            self.stdout.write(self.style.WARNING(f'Removidas: {", ".join(removidas)}'))
        self.stdout.write(self.style.SUCCESS('Partições em dia.'))
