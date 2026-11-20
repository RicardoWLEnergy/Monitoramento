"""
Preenche o "início da operação" das usinas já cadastradas, com a data da plataforma:
FoxESS = createDate (criação da usina) · Huawei = gridConnectionDate (conexão à rede).
Só mexe nas usinas ainda sem a data (as editadas pela equipe ficam como estão).

Uso:
    python manage.py preencher_inicio_operacao            (só mostra o que encontrou)
    python manage.py preencher_inicio_operacao --aplicar  (grava)

Atenção (Huawei): faz 1 login na conta Northbound; se o coletor estiver rodando, a sessão dele cai
e ele reconecta sozinho no próximo ciclo.
"""
from django.core.management.base import BaseCommand

from integracoes.cadastro import data_conexao_huawei, data_criacao_foxess
from integracoes.coleta import cliente_foxess
from integracoes.coleta_huawei import cliente_huawei
from integracoes.foxess import FoxESSErro
from integracoes.huawei import HuaweiErro
from usinas.models import Plataforma, Usina


class Command(BaseCommand):
    help = 'Preenche o início da operação das usinas (data de criação/conexão na plataforma).'

    def add_arguments(self, parser):
        parser.add_argument('--aplicar', action='store_true', help='Grava (sem isso, só mostra).')

    def handle(self, *args, **opcoes):
        usinas = list(Usina.objects.ativas().filter(inicio_operacao__isnull=True).order_by('plataforma', 'nome'))
        if not usinas:
            self.stdout.write('Todas as usinas já têm o início da operação.')
            return
        datas_huawei = {}
        if any(u.plataforma == Plataforma.HUAWEI for u in usinas):
            try:
                datas_huawei = {str(p.get('plantCode')): p.get('gridConnectionDate') for p in cliente_huawei().listar_usinas()}
            except (HuaweiErro, ValueError) as erro:
                self.stderr.write(f'Huawei indisponível: {erro}')
        foxess = None
        preenchidas = 0
        for usina in usinas:
            data = None
            if usina.plataforma == Plataforma.FOXESS:
                try:
                    foxess = foxess or cliente_foxess()
                    data = data_criacao_foxess((foxess.detalhe_usina(usina.id_externo) or {}).get('createDate'))
                except (FoxESSErro, ValueError) as erro:
                    self.stderr.write(f'{usina.nome}: FoxESS indisponível ({erro})')
            elif usina.plataforma == Plataforma.HUAWEI:
                data = data_conexao_huawei(datas_huawei.get(usina.id_externo), usina.fuso_horario)
            if not data:
                self.stdout.write(f'{usina.nome} ({usina.get_plataforma_display()}): a plataforma não informou a data')
                continue
            self.stdout.write(f'{usina.nome} ({usina.get_plataforma_display()}): início da operação {data:%d/%m/%Y}')
            if opcoes['aplicar']:
                Usina.objects.filter(pk=usina.pk).update(inicio_operacao=data)
            preenchidas += 1
        acao = 'Preenchidas' if opcoes['aplicar'] else 'Seriam preenchidas'
        self.stdout.write(self.style.SUCCESS(f'{acao}: {preenchidas} de {len(usinas)} usina(s).'))
        if not opcoes['aplicar'] and preenchidas:
            self.stdout.write('Para gravar, rode de novo com --aplicar.')
