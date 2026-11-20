"""
Preenche o clima do dia (ensolarado, nublado, chuvoso) das usinas ativas para os dias passados.
O coletor já atualiza ontem e hoje sozinho a cada 3 h, e a importação de histórico traz o clima do período;
este comando serve para completar o que já existia antes.

Uso:
    python manage.py atualizar_clima              (últimos 90 dias)
    python manage.py atualizar_clima --dias 400
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from integracoes.clima import ClimaErro, atualizar_clima
from usinas.models import Usina


class Command(BaseCommand):
    help = 'Preenche o clima do dia das usinas ativas (Open-Meteo) para os últimos N dias.'

    def add_arguments(self, parser):
        parser.add_argument('--dias', type=int, default=90, help='Quantos dias para trás (padrão 90, máximo 400).')

    def handle(self, *args, **opcoes):
        dias = min(max(opcoes['dias'], 1), 400)
        hoje = timezone.localdate()
        usinas = Usina.objects.ativas()
        sem_local = usinas.filter(latitude__isnull=True, cidade='').count()
        try:
            gravados = atualizar_clima(usinas, hoje - timedelta(days=dias - 1), hoje)
        except ClimaErro as erro:
            raise CommandError(f'Open-Meteo indisponível: {erro}') from None
        self.stdout.write(self.style.SUCCESS(f'Clima gravado: {gravados} registro(s) (usina × dia).'))
        if sem_local:
            self.stdout.write(f'{sem_local} usina(s) sem latitude/longitude e sem cidade ficaram de fora '
                              '(preencha em Configurações → Dados da usina).')
