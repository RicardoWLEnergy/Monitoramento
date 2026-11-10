"""Testes da API de usinas, por perfil."""
from datetime import datetime
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
        r = self.client.patch(f'/api/usinas/{self.minha.pk}/', {'limite_desempenho_pct': 70, 'nome': 'ignorado'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.data['limite_desempenho_pct'], r.data['nome']), (70, 'Usina do Cliente'))

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
        GeracaoDiaria.objects.create(usina=self.minha, data=hoje, energia_kwh=30)
        GeracaoEsperada.objects.create(usina=self.minha, mes=hoje.month, energia_kwh=900)
        self.entrar(self.cliente)
        meses = self.client.get(f'/api/usinas/{self.minha.pk}/geracao-mensal/?meses=3').data
        self.assertEqual(len(meses), 3)
        self.assertEqual((meses[-1]['gerado_kwh'], meses[-1]['esperado_kwh'], meses[-1]['parcial']),
                         (30.0, 900.0, True))

    def test_geracao_esperada_so_admin_altera(self):
        corpo = [{'mes': m, 'energia_kwh': 1000 + m} for m in range(1, 13)]
        url = f'/api/usinas/{self.minha.pk}/geracao-esperada/'
        self.entrar(self.colab)
        self.assertEqual(self.client.put(url, corpo, format='json').status_code, 403)
        self.entrar(self.admin)
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

    def test_colaborador_importa_periodo(self):
        from unittest.mock import patch
        hoje = timezone.localdate()
        with patch('usinas.views.importar_periodo', return_value={'dias_energia': 3, 'dias_curva': 3,
                                                                  'leituras': 800, 'falhas': []}) as importar:
            self.entrar(self.colab)
            r = self.client.post(self.url(), {'inicio': hoje.isoformat(), 'fim': hoje.isoformat()}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['leituras'], 800)
        self.assertIn('cobertura', r.data)
        importar.assert_called_once_with(self.minha, inicio=hoje, fim=hoje, curvas=True)

    def test_periodo_invalido(self):
        hoje = timezone.localdate()
        self.entrar(self.admin)
        futuro = (hoje.replace(year=hoje.year + 1)).isoformat()
        self.assertEqual(self.client.post(self.url(), {'inicio': hoje.isoformat(), 'fim': futuro}, format='json').status_code, 400)
        r = self.client.post(self.url(), {'inicio': '2020-01-01', 'fim': hoje.isoformat()}, format='json')
        self.assertEqual(r.status_code, 400)   # mais de 400 dias

    def test_erro_da_plataforma_vira_mensagem(self):
        from unittest.mock import patch
        from integracoes.huawei import HuaweiErro
        hoje = timezone.localdate().isoformat()
        self.entrar(self.admin)
        with patch('usinas.views.importar_periodo', side_effect=HuaweiErro('getKpiStationDay', 407)):
            r = self.client.post(self.url(), {'inicio': hoje, 'fim': hoje}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('407', r.data['detail'])


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
