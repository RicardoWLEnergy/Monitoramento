"""Testes da API de usinas, por perfil."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from rest_framework.test import APITestCase

from monitoramento.models import GeracaoDiaria, Leitura
from usuarios.models import Usuario

from .models import Fabricante, GeracaoEsperada, Inversor, Plataforma, Status, Usina


def criar_usina(**campos):
    dados = {'plataforma': Plataforma.FOXESS, 'fabricante': Fabricante.WEG, 'id_externo': 'X',
             'nome': 'Usina', 'potencia_kwp': 10}
    dados.update(campos)
    return Usina.objects.create(**dados)


class UsinasApiBase(APITestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user('admin@x.com', 'x', nome='Admin', perfil='admin')
        self.colab = Usuario.objects.create_user('colab@x.com', 'x', nome='Colab', perfil='colaborador')
        self.cliente = Usuario.objects.create_user('cli@x.com', 'x', nome='Cliente', perfil='cliente')
        self.outro = Usuario.objects.create_user('outro@x.com', 'x', nome='Outro', perfil='cliente')
        self.minha = criar_usina(id_externo='A', nome='Usina do Cliente', status=Status.ONLINE)
        self.alheia = criar_usina(id_externo='B', nome='Usina Alheia', status=Status.OFFLINE)
        self.minha.usuarios.add(self.cliente, self.outro)
        Inversor.objects.create(usina=self.minha, numero_serie='SN-MINHA', potencia_atual_kw=4, geracao_hoje_kwh=20)

    def entrar(self, usuario):
        self.client.force_authenticate(usuario)

    def nomes(self, resposta):
        return [u['nome'] for u in resposta.data['results']]


class UsinasApiTests(UsinasApiBase):
    def test_nao_se_cria_usina_pela_api(self):
        # Usinas só entram pelo cadastro do cliente + SN
        self.entrar(self.admin)
        self.assertEqual(self.client.post('/api/usinas/', {'nome': 'X'}, format='json').status_code, 405)

    def test_cliente_so_ve_as_suas(self):
        self.entrar(self.cliente)
        self.assertEqual(self.nomes(self.client.get('/api/usinas/')), ['Usina do Cliente'])
        self.assertEqual(self.client.get(f'/api/usinas/{self.alheia.pk}/').status_code, 404)

    def test_equipe_ve_todas(self):
        for usuario in (self.admin, self.colab):
            self.entrar(usuario)
            self.assertEqual(len(self.client.get('/api/usinas/').data['results']), 2)

    def test_lista_traz_valores_calculados(self):
        self.entrar(self.cliente)
        item = self.client.get('/api/usinas/').data['results'][0]
        self.assertEqual((item['potencia_atual_kw'], item['geracao_hoje_kwh']), (4.0, 20.0))

    def test_filtros_busca_por_sn_e_status(self):
        self.entrar(self.admin)
        self.assertEqual(self.nomes(self.client.get('/api/usinas/?busca=sn-minha')), ['Usina do Cliente'])
        self.assertEqual(self.nomes(self.client.get('/api/usinas/?status=offline')), ['Usina Alheia'])
        self.assertEqual(self.nomes(self.client.get('/api/usinas/?ordem=-nome')), ['Usina do Cliente', 'Usina Alheia'])

    def test_resumo(self):
        self.entrar(self.admin)
        r = self.client.get('/api/usinas/resumo/').data
        self.assertEqual((r['total'], r['online'], r['offline']), (2, 1, 1))

    def test_alertas_so_admin_altera(self):
        self.entrar(self.colab)
        r = self.client.patch(f'/api/usinas/{self.minha.pk}/', {'limite_desempenho_pct': 70})
        self.assertEqual(r.status_code, 403)
        self.entrar(self.admin)
        r = self.client.patch(f'/api/usinas/{self.minha.pk}/', {'limite_desempenho_pct': 70, 'plataforma': 'huawei'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['limite_desempenho_pct'], r.data['plataforma']), (70, 'foxess'))   # plataforma não muda

    def test_equipe_edita_dados_cadastrais(self):
        dados = {'nome': 'UFV Corrigida', 'cidade': 'Brasília', 'uf': 'df', 'potencia_kwp': 119.6,
                 'latitude': -15.8, 'longitude': -47.9, 'endereco': 'SIA Trecho 1'}
        self.entrar(self.colab)
        r = self.client.patch(f'/api/usinas/{self.minha.pk}/', dados, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['nome'], r.data['uf'], float(r.data['potencia_kwp'])), ('UFV Corrigida', 'DF', 119.6))
        self.assertIn('-15.8', r.data['link_maps'])

    def test_cliente_nao_edita_usina(self):
        self.entrar(self.cliente)
        r = self.client.patch(f'/api/usinas/{self.minha.pk}/', {'nome': 'Minha'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_validacoes_da_edicao(self):
        self.entrar(self.admin)
        url = f'/api/usinas/{self.minha.pk}/'
        self.assertEqual(self.client.patch(url, {'nome': '  '}, format='json').status_code, 400)
        self.assertEqual(self.client.patch(url, {'fuso_horario': 'Lua/Base'}, format='json').status_code, 400)

    def test_vincular_clientes(self):
        self.entrar(self.colab)
        r = self.client.put(f'/api/usinas/{self.alheia.pk}/clientes/', {'clientes': [self.cliente.pk]}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c['email'] for c in r.data['clientes']], ['cli@x.com'])
        r = self.client.put(f'/api/usinas/{self.alheia.pk}/clientes/', {'clientes': [self.colab.pk]}, format='json')
        self.assertEqual(r.status_code, 400)
        self.entrar(self.cliente)
        r = self.client.put(f'/api/usinas/{self.minha.pk}/clientes/', {'clientes': []}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_cliente_nao_ve_outros_clientes_da_usina(self):
        self.entrar(self.cliente)
        self.assertNotIn('clientes', self.client.get(f'/api/usinas/{self.minha.pk}/').data)
        self.entrar(self.admin)
        self.assertEqual(len(self.client.get(f'/api/usinas/{self.minha.pk}/').data['clientes']), 2)

    def test_inversores(self):
        self.entrar(self.cliente)
        r = self.client.get(f'/api/usinas/{self.minha.pk}/inversores/')
        self.assertEqual([i['numero_serie'] for i in r.data], ['SN-MINHA'])

    def test_curva_do_dia_no_fuso_da_usina(self):
        hoje = timezone.localdate()
        dez_e_meia = datetime(hoje.year, hoje.month, hoje.day, 10, 30, tzinfo=ZoneInfo('America/Sao_Paulo'))
        Leitura.objects.create(usina=self.minha, data_hora=dez_e_meia, potencia_kw=5.5)
        self.entrar(self.cliente)
        r = self.client.get(f'/api/usinas/{self.minha.pk}/curva/?data={hoje.isoformat()}')
        self.assertEqual(r.data['pontos'], [{'hora': '10:30', 'kw': 5.5}])
        self.assertEqual(self.client.get(f'/api/usinas/{self.minha.pk}/curva/?data=ontem').status_code, 400)

    def test_geracao_mensal_e_esperado(self):
        hoje = timezone.localdate()
        GeracaoDiaria.objects.create(usina=self.minha, data=hoje - timedelta(days=120), energia_kwh=5)   # já operava
        GeracaoDiaria.objects.create(usina=self.minha, data=hoje, energia_kwh=30)
        GeracaoEsperada.objects.create(usina=self.minha, mes=hoje.month, energia_kwh=900)
        self.entrar(self.cliente)
        meses = self.client.get(f'/api/usinas/{self.minha.pk}/geracao-mensal/?meses=3').data
        self.assertEqual(len(meses), 3)
        self.assertEqual((meses[-1]['gerado_kwh'], meses[-1]['esperado_kwh'], meses[-1]['parcial']),
                         (30.0, 900.0, True))

    def test_geracao_esperada_equipe_altera_cliente_nao(self):
        corpo = [{'mes': m, 'energia_kwh': 1000 + m} for m in range(1, 13)]
        url = f'/api/usinas/{self.minha.pk}/geracao-esperada/'
        self.entrar(self.cliente)
        self.assertEqual(self.client.put(url, corpo, format='json').status_code, 403)
        for usuario in (self.colab, self.admin):
            self.entrar(usuario)
            r = self.client.put(url, corpo, format='json')
            self.assertEqual((r.status_code, len(r.data)), (200, 12))


class ImportarHistoricoApiTests(UsinasApiBase):
    """Botão 'Importar histórico' (Admin e Colaborador)."""

    def url(self):
        return f'/api/usinas/{self.minha.pk}/historico/'

    def test_cliente_nao_acessa(self):
        self.entrar(self.cliente)
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_colaborador_ve_cobertura(self):
        self.entrar(self.colab)
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['energia_diaria']['dias'], r.data['inversores']), (0, 1))

    def test_colaborador_pede_importacao_e_ela_vai_para_a_fila(self):
        from monitoramento.models import ImportacaoHistorico
        hoje = timezone.localdate()
        self.entrar(self.colab)
        r = self.client.post(self.url(), {'inicio': hoje.isoformat(), 'fim': hoje.isoformat()}, format='json')
        self.assertEqual(r.status_code, 202)                    # responde na hora: quem importa é o coletor
        self.assertEqual(r.data['importacao']['status'], 'fila')
        self.assertIn('energia_diaria', r.data)                 # junto com o que já existe no banco
        imp = ImportacaoHistorico.objects.get()
        self.assertEqual((imp.usina, imp.inicio, imp.fim, imp.curvas, imp.solicitado_por),
                         (self.minha, hoje, hoje, True, self.colab))
        self.assertEqual(self.client.get(self.url()).data['importacao']['id'], imp.pk)   # a tela acompanha pelo GET

    def test_uma_importacao_ativa_por_usina(self):
        hoje = timezone.localdate().isoformat()
        self.entrar(self.admin)
        self.assertEqual(self.client.post(self.url(), {'inicio': hoje, 'fim': hoje}, format='json').status_code, 202)
        r = self.client.post(self.url(), {'inicio': hoje, 'fim': hoje}, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertIn('em andamento', r.data['detail'])

    def test_depois_de_concluida_pode_pedir_outra(self):
        from monitoramento.models import ImportacaoHistorico
        hoje = timezone.localdate().isoformat()
        self.entrar(self.admin)
        self.client.post(self.url(), {'inicio': hoje, 'fim': hoje}, format='json')
        ImportacaoHistorico.objects.update(status=ImportacaoHistorico.Status.CONCLUIDA)
        self.assertEqual(self.client.post(self.url(), {'inicio': hoje, 'fim': hoje}, format='json').status_code, 202)

    def test_pedido_comeca_no_inicio_da_operacao(self):
        from monitoramento.models import ImportacaoHistorico
        hoje = timezone.localdate()
        self.minha.inicio_operacao = hoje - timedelta(days=6)
        self.minha.save()
        self.entrar(self.colab)
        r = self.client.post(self.url(), {'inicio': (hoje - timedelta(days=364)).isoformat(), 'fim': hoje.isoformat()},
                             format='json')
        self.assertEqual(r.status_code, 202)
        self.assertEqual(ImportacaoHistorico.objects.get().inicio, hoje - timedelta(days=6))   # só os 7 dias
        ImportacaoHistorico.objects.all().delete()
        r = self.client.post(self.url(), {'inicio': (hoje - timedelta(days=30)).isoformat(),
                                          'fim': (hoje - timedelta(days=10)).isoformat()}, format='json')
        self.assertEqual(r.status_code, 400)                                  # todo o período antes de ligar
        self.assertIn('começou a operar', r.data['detail'])

    def test_equipe_corrige_o_inicio_da_operacao(self):
        self.entrar(self.colab)
        r = self.client.patch(f'/api/usinas/{self.minha.pk}/', {'inicio_operacao': '2025-01-15'}, format='json')
        self.assertEqual((r.status_code, r.data['inicio_operacao']), (200, '2025-01-15'))

    def test_periodo_invalido(self):
        hoje = timezone.localdate()
        self.entrar(self.admin)
        futuro = (hoje.replace(year=hoje.year + 1)).isoformat()
        self.assertEqual(self.client.post(self.url(), {'inicio': hoje.isoformat(), 'fim': futuro}, format='json').status_code, 400)
        r = self.client.post(self.url(), {'inicio': '2020-01-01', 'fim': hoje.isoformat()}, format='json')
        self.assertEqual(r.status_code, 400)   # mais de 400 dias


class GeracaoDiariaApiTests(UsinasApiBase):
    """Gráfico 'Período' da usina: energia de cada dia."""

    def url(self, usina=None, **params):
        from urllib.parse import urlencode
        return f'/api/usinas/{(usina or self.minha).pk}/geracao-diaria/?{urlencode(params)}'

    def test_cliente_ve_os_dias_da_sua_usina_com_dias_sem_dado(self):
        from datetime import date
        GeracaoDiaria.objects.create(usina=self.minha, data=date(2026, 11, 1), energia_kwh='288.400')
        GeracaoDiaria.objects.create(usina=self.minha, data=date(2026, 11, 3), energia_kwh='301.250')
        GeracaoEsperada.objects.create(usina=self.minha, mes=11, energia_kwh=9000)   # 9.000 ÷ 30 dias = 300/dia
        self.entrar(self.cliente)
        r = self.client.get(self.url(inicio='2026-11-01', fim='2026-11-03'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['dias'], [
            {'data': '2026-11-01', 'kwh': 288.4, 'esperado_kwh': 300.0},
            {'data': '2026-11-02', 'kwh': None, 'esperado_kwh': 300.0},     # sem dado: não vira zero
            {'data': '2026-11-03', 'kwh': 301.25, 'esperado_kwh': 300.0},
        ])

    def test_sem_geracao_esperada_o_esperado_do_dia_e_vazio(self):
        from datetime import date
        GeracaoDiaria.objects.create(usina=self.minha, data=date(2026, 10, 31), energia_kwh=10)
        self.entrar(self.admin)
        r = self.client.get(self.url(inicio='2026-10-31', fim='2026-10-31'))
        self.assertEqual(r.data['dias'], [{'data': '2026-10-31', 'kwh': 10.0, 'esperado_kwh': None}])

    def test_cliente_nao_ve_usina_alheia(self):
        self.entrar(self.cliente)
        self.assertEqual(self.client.get(self.url(self.alheia)).status_code, 404)

    def test_padrao_ultimos_30_dias_e_futuro_vira_hoje(self):
        from datetime import timedelta
        hoje = timezone.localdate()
        self.entrar(self.admin)
        r = self.client.get(self.url())
        self.assertEqual((len(r.data['dias']), r.data['fim']), (30, hoje.isoformat()))
        r = self.client.get(self.url(inicio=hoje.isoformat(), fim=(hoje + timedelta(days=5)).isoformat()))
        self.assertEqual(r.data['fim'], hoje.isoformat())

    def test_periodo_invalido(self):
        self.entrar(self.admin)
        self.assertEqual(self.client.get(self.url(inicio='2026-11-05', fim='2026-11-01')).status_code, 400)
        self.assertEqual(self.client.get(self.url(inicio='2024-01-01', fim='2026-11-01')).status_code, 400)
        self.assertEqual(self.client.get(self.url(inicio='ontem')).status_code, 400)


class EntradasInvalidasApiTests(UsinasApiBase):
    """Parâmetros estranhos na URL respondem 400 (ou são ignorados), nunca erro 500."""

    def test_parametros_invalidos(self):
        self.entrar(self.admin)
        base = f'/api/usinas/{self.minha.pk}'
        self.assertEqual(self.client.get(f'{base}/geracao-mensal/?meses=abc').status_code, 200)
        self.assertEqual(self.client.get(f'{base}/curva/?data=9999-12-31').status_code, 400)
        self.assertEqual(self.client.get(f'{base}/geracao-diaria/?fim=0001-01-05').status_code, 400)
        self.assertEqual(self.client.get('/api/dashboard/curva/?data=1-1-1').status_code, 400)
        self.assertEqual(self.client.get('/api/alertas/?usina=abc').status_code, 200)


class ApagarUsinaApiTests(UsinasApiBase):
    """'Apagar' = desativar: some do sistema, mas o histórico fica no banco."""

    def test_so_admin_apaga(self):
        for usuario in (self.colab, self.cliente):
            self.entrar(usuario)
            self.assertEqual(self.client.delete(f'/api/usinas/{self.minha.pk}/').status_code, 403)

    def test_apagar_desativa_mantem_historico_e_remove_vinculos(self):
        GeracaoDiaria.objects.create(usina=self.minha, data=timezone.localdate(), energia_kwh=10)
        self.entrar(self.admin)
        self.assertEqual(self.client.delete(f'/api/usinas/{self.minha.pk}/').status_code, 204)

        self.minha.refresh_from_db()
        self.assertFalse(self.minha.ativa)
        self.assertIsNotNone(self.minha.desativada_em)
        self.assertEqual(self.minha.usuarios.count(), 0)                         # vínculos removidos
        self.assertEqual(GeracaoDiaria.objects.filter(usina=self.minha).count(), 1)   # histórico fica
        self.assertTrue(Inversor.objects.filter(usina=self.minha).exists())

    def test_usina_desativada_some_de_tudo(self):
        self.minha.desativar()
        self.entrar(self.admin)
        self.assertNotIn('Usina do Cliente', self.nomes(self.client.get('/api/usinas/')))
        self.assertEqual(self.client.get(f'/api/usinas/{self.minha.pk}/').status_code, 404)
        self.assertEqual(self.client.get('/api/usinas/resumo/').data['total'], 1)
        self.assertEqual(self.client.get('/api/dashboard/').data['kpis']['total'], 1)
        self.entrar(self.cliente)
        self.assertEqual(self.client.get('/api/usinas/').data['results'], [])
