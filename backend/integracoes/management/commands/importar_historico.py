"""
Importa o histórico de geração das usinas cadastradas (FoxESS e Huawei).

Uso:
    python manage.py importar_historico                    (todas as usinas ativas)
    python manage.py importar_historico --usina 1          (só a usina de id 1)
    python manage.py importar_historico --meses 13 --dias 30

- --meses: energia de cada dia dos últimos N meses (padrão 13 = mês atual + 12)
- --dias:  curva de 5 min dos últimos N dias (padrão 30)
Pode ser repetido: o que já existe é atualizado, nada é duplicado.
O mesmo processo existe na tela: Usina → Configurações → Histórico de geração.
"""
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from integracoes.coleta import importar_periodo
from integracoes.foxess import FoxESSErro
from integracoes.huawei import HuaweiErro
from usinas.models import Usina


class Command(BaseCommand):
    help = 'Importa o histórico de geração (energia diária e curvas de 5 min) das usinas ativas.'

    def add_arguments(self, parser):
        parser.add_argument('--usina', type=int, help='ID da usina (padrão: todas as ativas).')
        parser.add_argument('--meses', type=int, default=13, help='Meses de energia diária (padrão 13).')
        parser.add_argument('--dias', type=int, default=30, help='Dias de curva de 5 min (padrão 30).')

    def handle(self, *args, **opcoes):
        usinas = Usina.objects.ativas()
        if opcoes['usina']:
            usinas = usinas.filter(pk=opcoes['usina'])
        if not usinas.exists():
            raise CommandError('Nenhuma usina ativa cadastrada (ou ID não encontrado).')

        hoje = timezone.localdate()
        total = hoje.year * 12 + hoje.month - 1 - (opcoes['meses'] - 1)
        inicio_energia = date(total // 12, total % 12 + 1, 1)
        inicio_curvas = hoje - timedelta(days=opcoes['dias'] - 1)

        for usina in usinas:
            self.stdout.write(self.style.MIGRATE_HEADING(f'\n{usina.nome} ({usina.get_plataforma_display()})'))
            try:
                energia = importar_periodo(usina, inicio_energia, hoje, curvas=False)
                self.stdout.write(f"  Energia diária: {energia['dias_energia']} dia(s) ({opcoes['meses']} meses)")
                curvas = importar_periodo(usina, inicio_curvas, hoje, curvas=True)
                self.stdout.write(f"  Curvas de 5 min: {curvas['dias_curva']} dia(s), {curvas['leituras']} leitura(s)")
            except (FoxESSErro, HuaweiErro, ValueError) as erro:
                self.stdout.write(self.style.ERROR(f'  ! {erro}'))
                continue
            for falha in (energia['falhas'] + curvas['falhas'])[:5]:
                self.stdout.write(self.style.WARNING(f'  ! {falha}'))

        self.stdout.write(self.style.SUCCESS('\nHistórico importado.'))
