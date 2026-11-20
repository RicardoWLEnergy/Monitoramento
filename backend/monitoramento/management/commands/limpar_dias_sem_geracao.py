"""
Remove dados zerados gravados ANTES de cada usina começar a operar (início da operação; sem ele, 1º dia com geração):
energia diária = 0 e leituras de 5 min = 0 kW. Depois do início da operação nada é tocado
(um dia parado é informação).

Uso:
    python manage.py limpar_dias_sem_geracao            (só mostra o que seria apagado)
    python manage.py limpar_dias_sem_geracao --aplicar  (apaga)
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand
from django.db import transaction

from monitoramento.consultas import inicio_operacao_por_usina
from monitoramento.models import GeracaoDiaria, Leitura
from usinas.models import Usina


class Command(BaseCommand):
    help = 'Remove energia diária e leituras zeradas de antes do início da operação de cada usina.'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Apaga de verdade (sem isso, só mostra).')

    def handle(self, *args, **opcoes):
        usinas = Usina.objects.all()
        inicio = inicio_operacao_por_usina(usinas)
        total_dias = total_leituras = 0
        for usina in usinas.order_by('nome'):
            primeiro = inicio.get(usina.pk)
            if not primeiro:
                continue   # nunca gerou: pode ser recém-cadastrada; não mexe
            comeco = datetime(primeiro.year, primeiro.month, primeiro.day, tzinfo=ZoneInfo(usina.fuso_horario))
            dias = GeracaoDiaria.objects.filter(usina=usina, data__lt=primeiro, energia_kwh=0)
            leituras = Leitura.objects.filter(usina=usina, data_hora__lt=comeco, potencia_kw=0)
            n_dias, n_leituras = dias.count(), leituras.count()
            if not (n_dias or n_leituras):
                continue
            self.stdout.write(f'{usina.nome}: opera desde {primeiro:%d/%m/%Y} — '
                              f'{n_dias} dia(s) de energia e {n_leituras} leitura(s) zerados antes disso')
            if opcoes['aplicar']:
                with transaction.atomic():
                    dias.delete()
                    leituras.delete()
            total_dias += n_dias
            total_leituras += n_leituras
        acao = 'Apagados' if opcoes['aplicar'] else 'Seriam apagados'
        self.stdout.write(self.style.SUCCESS(f'{acao}: {total_dias} dia(s) de energia e {total_leituras} leitura(s).'))
        if not opcoes['aplicar'] and (total_dias or total_leituras):
            self.stdout.write('Para apagar, rode de novo com --aplicar.')
