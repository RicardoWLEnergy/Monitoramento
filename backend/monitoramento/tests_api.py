"""Testes da API do dashboard e dos alertas, por perfil."""
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from usinas.models import Fabricante, GeracaoEsperada, Plataforma, Status, Usina
from usuarios.models import Usuario

from .models import Alerta, GeracaoDiaria, Leitura


class DashboardEAlertasApiTests(APITestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user('admin@x.com', 'x', nome='Admin', perfil='admin')
        self.cliente = Usuario.objects.create_user('cli@x.com', 'x', nome='Cliente', perfil='cliente')
        comum = {'plataforma': Plataforma.FOXESS, 'fabricante': Fabricante.WEG}
        self.minha = Usina.objects.create(**comum, id_externo='A', nome='Minha', potencia_kwp=10, status=Status.ALERTA)
        self.alheia = Usina.objects.create(**comum, id_externo='B', nome='Alheia', potencia_kwp=50, status=Status.OFFLINE)
        self.minha.usuarios.add(self.cliente)
        hoje = timezone.localdate()
        GeracaoDiaria.objects.create(usina=self.minha, data=hoje, energia_kwh=40)
        GeracaoEsperada.objects.create(usina=self.minha, mes=hoje.month, energia_kwh=80)
        Alerta.objects.create(usina=self.minha, tipo=Alerta.Tipo.BAIXO_DESEMPENHO, mensagem='Inversor 2 abaixo')
        Alerta.objects.create(usina=self.alheia, tipo=Alerta.Tipo.OFFLINE)

    def test_cliente_nao_acessa_a_visao_geral(self):
        self.client.force_authenticate(self.cliente)
        self.assertEqual(self.client.get('/api/dashboard/').status_code, 403)

    def test_dashboard_da_equipe_com_todas(self):
        self.client.force_authenticate(self.admin)
        d = self.client.get('/api/dashboard/').data
        self.assertEqual((d['kpis']['total'], d['kpis']['offline'], d['kpis']['alerta']), (2, 1, 1))
        self.assertEqual(d['kpis']['potencia_instalada_kwp'], 60.0)
        self.assertEqual(d['atencao'][0]['nome'], 'Alheia')   # offline vem primeiro
        self.assertEqual([a['motivo'] for a in d['atencao']], ['Sem comunicação', 'Inversor 2 abaixo'])
        self.assertEqual(d['menor_desempenho'], [{'id': self.minha.pk, 'nome': 'Minha', 'pct': 50.0}])
        self.assertEqual(len(d['geracao_mensal']), 12)

    def test_colaborador_tambem_ve_a_visao_geral(self):
        colab = Usuario.objects.create_user('colab@x.com', 'x', nome='Colab', perfil='colaborador')
        self.client.force_authenticate(colab)
        self.assertEqual(self.client.get('/api/dashboard/').data['kpis']['total'], 2)

    def test_curva_da_carteira_soma_em_blocos_de_5_min(self):
        dez_e_trinta_e_um = timezone.localtime().replace(hour=10, minute=31, second=0, microsecond=0)
        Leitura.objects.create(usina=self.minha, data_hora=dez_e_trinta_e_um, potencia_kw=2)
        Leitura.objects.create(usina=self.alheia, data_hora=dez_e_trinta_e_um + timedelta(minutes=2), potencia_kw=3)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/dashboard/').data['curva_hoje'], [{'hora': '10:30', 'kw': 5.0}])

    def test_alertas_do_cliente(self):
        self.client.force_authenticate(self.cliente)
        r = self.client.get('/api/alertas/?aberto=true')
        self.assertEqual([a['usina_nome'] for a in r.data['results']], ['Minha'])

    def test_usina_a_noite_nao_precisa_de_atencao(self):
        self.alheia.status = Status.NOITE
        self.alheia.save()
        self.client.force_authenticate(self.admin)
        d = self.client.get('/api/dashboard/').data
        self.assertEqual([a['nome'] for a in d['atencao']], ['Minha'])
        self.assertEqual(d['kpis']['noite'], 1)
