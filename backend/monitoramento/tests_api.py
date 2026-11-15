"""Testes da API do dashboard e dos alertas, por perfil."""
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from usinas.models import Fabricante, GeracaoEsperada, Plataforma, Status, Usina
from usuarios.models import Usuario

from .consultas import fracao_do_mes, geracao_mensal
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
        # 40 kWh gerados × esperado ATÉ HOJE (80 kWh do mês proporcional aos dias passados)
        pct = round(40 / (80 * fracao_do_mes(timezone.localdate())) * 100, 1)
        self.assertEqual(d['menor_desempenho'], [{'id': self.minha.pk, 'nome': 'Minha', 'pct': pct}])
        self.assertEqual(d['kpis']['desempenho_mes_pct'], pct)
        self.assertEqual(d['kpis']['esperado_mes_kwh'], 80.0)
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

    def test_periodo_soma_as_usinas_por_dia(self):
        hoje = timezone.localdate()
        GeracaoDiaria.objects.create(usina=self.alheia, data=hoje, energia_kwh=60)
        self.client.force_authenticate(self.admin)
        r = self.client.get(f'/api/dashboard/geracao-diaria/?inicio={hoje - timedelta(days=1)}&fim={hoje}')
        ontem = hoje - timedelta(days=1)
        import calendar
        por_dia = lambda d: round(80 / calendar.monthrange(d.year, d.month)[1], 3) if d.month == hoje.month else None
        self.assertEqual(r.data['dias'], [
            {'data': ontem.isoformat(), 'kwh': None, 'esperado_kwh': por_dia(ontem)},
            {'data': hoje.isoformat(), 'kwh': 100.0, 'esperado_kwh': por_dia(hoje)},   # só a "Minha" tem esperado (80/mês)
        ])
        self.assertEqual(self.client.get('/api/dashboard/geracao-diaria/?inicio=2020-01-01').status_code, 400)

    def test_curva_da_carteira_de_outro_dia(self):
        ontem = timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=1)
        Leitura.objects.create(usina=self.minha, data_hora=ontem, potencia_kw=7)
        self.client.force_authenticate(self.admin)
        r = self.client.get(f'/api/dashboard/curva/?data={ontem.date()}')
        self.assertEqual(r.data['pontos'], [{'hora': '12:00', 'kw': 7.0}])

    def test_cliente_nao_acessa_periodo_nem_curva_da_carteira(self):
        self.client.force_authenticate(self.cliente)
        self.assertEqual(self.client.get('/api/dashboard/geracao-diaria/').status_code, 403)
        self.assertEqual(self.client.get('/api/dashboard/curva/').status_code, 403)

    def test_esperado_ate_hoje_e_proporcional_aos_dias_do_mes(self):
        from datetime import date
        self.assertEqual(fracao_do_mes(date(2026, 11, 15)), 0.5)       # 15 de 30 dias
        self.assertEqual(fracao_do_mes(date(2026, 2, 28)), 1.0)        # último dia: mês inteiro
        GeracaoEsperada.objects.create(usina=self.minha, mes=10, energia_kwh=310)
        meses = geracao_mensal(Usina.objects.filter(pk=self.minha.pk), 2, hoje=date(2026, 11, 15))
        self.assertEqual([(m['esperado_kwh'], m['esperado_ate_hoje_kwh'], m['parcial']) for m in meses],
                         [(310.0, 310.0, False), (80.0, 40.0, True)])   # mês fechado: inteiro; mês atual: metade

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
