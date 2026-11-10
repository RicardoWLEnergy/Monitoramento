import hashlib
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings

from usinas.models import Fabricante, Inversor, Plataforma, Status, Usina
from usuarios.models import Usuario

from .cadastro import CadastroErro, cadastrar_por_sn, fabricante_pelo_modelo
from .foxess import FoxESSCliente, FoxESSErro


def resposta(json_data, status=200):
    r = MagicMock(status_code=status)
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


class FoxESSAssinaturaTests(SimpleTestCase):
    """Sem rede: só confere as regras da documentação oficial."""

    def setUp(self):
        self.cliente = FoxESSCliente('https://www.foxesscloud.com', 'CHAVE')
        self.cliente.INTERVALO_POR_ENDPOINT = 0

    def test_assinatura_usa_barra_r_barra_n_literais(self):
        esperado = hashlib.md5('/op/v0/plant/list\\r\\nCHAVE\\r\\n1700000000000'.encode()).hexdigest()
        self.assertEqual(self.cliente.assinatura('/op/v0/plant/list', '1700000000000'), esperado)

    def test_assinatura_nao_usa_quebra_de_linha_real(self):
        errado = hashlib.md5('/op/v0/plant/list\r\nCHAVE\r\n1700000000000'.encode()).hexdigest()
        self.assertNotEqual(self.cliente.assinatura('/op/v0/plant/list', '1700000000000'), errado)

    def test_assina_so_o_path(self):
        with patch.object(self.cliente.sessao, 'request', return_value=resposta({'errno': 0, 'result': {}})) as req:
            self.cliente.geracao('SN1')
        cab = req.call_args.kwargs['headers']
        self.assertEqual(cab['signature'], self.cliente.assinatura('/op/v0/device/generation', cab['timestamp']))
        self.assertEqual(req.call_args.kwargs['params'], {'sn': 'SN1'})

    def test_errno_diferente_de_zero_vira_erro(self):
        with patch.object(self.cliente.sessao, 'request', return_value=resposta({'errno': 40400, 'msg': 'x'})):
            with self.assertRaises(FoxESSErro) as ctx:
                self.cliente.cota()
        self.assertTrue(ctx.exception.e_limite)

    def test_tempo_real_divide_em_lotes_de_50(self):
        sns = [f'SN{i}' for i in range(120)]
        with patch.object(self.cliente.sessao, 'request', return_value=resposta({'errno': 0, 'result': []})) as req:
            self.cliente.tempo_real(sns)
        lotes = [len(c.kwargs['json']['sns']) for c in req.call_args_list]
        self.assertEqual(lotes, [50, 50, 20])

    def test_paginacao_ate_o_total(self):
        paginas = [
            resposta({'errno': 0, 'result': {'data': [{'stationID': i} for i in range(100)], 'pageSize': 100, 'total': 150}}),
            resposta({'errno': 0, 'result': {'data': [{'stationID': i} for i in range(50)], 'pageSize': 100, 'total': 150}}),
        ]
        with patch.object(self.cliente.sessao, 'request', side_effect=paginas):
            self.assertEqual(len(self.cliente.listar_usinas()), 150)

    def test_sem_chave_avisa(self):
        with self.assertRaises(ValueError):
            FoxESSCliente('https://www.foxesscloud.com', '')


# ---------------------------------------------------------------------------
# Cadastro de usina pela SN (API simulada, sem rede)
# ---------------------------------------------------------------------------
USINA_FOX = {
    'stationName': 'UFV WL Energy', 'city': 'Brasilia', 'country': 'BR',
    'address': 'CA V Pires Ch 29 Lt 01-02', 'capacity': 97.9, 'timezone': 'America/Sao_Paulo',
    'modules': [{'moduleSN': 'M1', 'deviceSN': 'SN-A'}, {'moduleSN': 'M2', 'deviceSN': 'SN-B'}],
}
# Lista de inversores da conta (fonte principal do cadastro)
LISTA_FOX = [
    {'deviceSN': 'SN-A', 'stationID': 'st-1', 'stationName': 'UFV WL Energy', 'status': 1, 'deviceType': 'SIW200G M050 W1'},
    {'deviceSN': 'SN-B', 'stationID': 'st-1', 'stationName': 'UFV WL Energy', 'status': 3, 'deviceType': 'SIW200G M050 W1'},
    {'deviceSN': 'SN-OUTRA', 'stationID': 'st-2', 'stationName': 'Outra usina', 'status': 1, 'deviceType': 'T10-G3'},
]
# Detalhe (opcional): SN-B simula o erro real 41200 da FoxESS
INVERSORES_FOX = {'SN-A': {'deviceSN': 'SN-A', 'stationID': 'st-1', 'capacity': 50}}


def detalhe_inversor_simulado(sn):
    if sn not in INVERSORES_FOX:
        raise FoxESSErro('/op/v1/device/detail', 41200)   # "Unable to load data"
    return INVERSORES_FOX[sn]


def api_fox_simulada():
    api = MagicMock()
    api.detalhe_inversor.side_effect = detalhe_inversor_simulado
    api.detalhe_usina.return_value = USINA_FOX
    api.listar_inversores.return_value = LISTA_FOX
    return api


@override_settings(FOXESS_API_KEY='CHAVE-TESTE')
@patch('integracoes.cadastro.FoxESSCliente')
class CadastroPorSnTests(TestCase):
    def setUp(self):
        self.cliente = Usuario.objects.create_user('cli@x.com', 'x', nome='Cliente 1')

    def test_cadastra_usina_inteira_e_vincula(self, Cliente):
        Cliente.return_value = api_fox_simulada()
        r = cadastrar_por_sn(Plataforma.FOXESS, ' sn-a ', self.cliente)   # espaços/minúsculas tolerados

        self.assertTrue(r.usina_nova)
        self.assertEqual(r.inversores, ['SN-A', 'SN-B'])                    # os 2 inversores da usina
        u = Usina.objects.get()
        self.assertEqual((u.nome, u.id_externo, u.plataforma), ('UFV WL Energy', 'st-1', Plataforma.FOXESS))
        self.assertEqual(u.fabricante, Fabricante.WEG)                       # SIW… = WEG
        self.assertEqual(str(u.potencia_kwp), '97.90')
        self.assertEqual(u.status, Status.ONLINE)                            # 1 online + 1 offline
        self.assertEqual(Inversor.objects.get(numero_serie='SN-A').modelo, 'SIW200G M050 W1')
        self.assertEqual(list(self.cliente.usinas.all()), [u])
        self.assertFalse(Inversor.objects.filter(numero_serie='SN-OUTRA').exists())   # só a usina certa

    def test_detalhe_do_inversor_com_erro_nao_impede_o_cadastro(self, Cliente):
        Cliente.return_value = api_fox_simulada()
        cadastrar_por_sn(Plataforma.FOXESS, 'SN-B', self.cliente)            # SN-B: detalhe dá 41200
        self.assertEqual(str(Inversor.objects.get(numero_serie='SN-B').potencia_nominal_kw), '0.00')
        self.assertEqual(str(Inversor.objects.get(numero_serie='SN-A').potencia_nominal_kw), '50.00')

    def test_modelo_desconhecido_vira_vazio(self, Cliente):
        api = api_fox_simulada()
        api.listar_inversores.return_value = [{'deviceSN': 'SN-A', 'stationID': 'st-1', 'status': 1, 'deviceType': '--'}]
        Cliente.return_value = api
        cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', self.cliente)
        self.assertEqual(Inversor.objects.get(numero_serie='SN-A').modelo, '')
        self.assertEqual(Usina.objects.get().fabricante, Fabricante.FOXESS)

    def test_cadastrar_de_novo_nao_duplica(self, Cliente):
        Cliente.return_value = api_fox_simulada()
        cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', self.cliente)
        r = cadastrar_por_sn(Plataforma.FOXESS, 'SN-B', self.cliente)       # outra SN da mesma usina
        self.assertFalse(r.usina_nova)
        self.assertTrue(r.ja_vinculado)
        self.assertEqual((Usina.objects.count(), Inversor.objects.count()), (1, 2))

    def test_segundo_cliente_na_mesma_usina(self, Cliente):
        Cliente.return_value = api_fox_simulada()
        outro = Usuario.objects.create_user('cli2@x.com', 'x', nome='Cliente 2')
        cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', self.cliente)
        cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', outro)
        self.assertEqual(Usina.objects.get().usuarios.count(), 2)

    def test_nao_altera_config_de_alerta_nem_outros_vinculos(self, Cliente):
        Cliente.return_value = api_fox_simulada()
        cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', self.cliente)
        Usina.objects.update(limite_desempenho_pct=70, alertas_ativos=False)
        outro = Usuario.objects.create_user('cli2@x.com', 'x', nome='Cliente 2')
        cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', outro)
        u = Usina.objects.get()
        self.assertEqual((u.limite_desempenho_pct, u.alertas_ativos), (70, False))
        self.assertIn(self.cliente, u.usuarios.all())

    def test_sn_de_outra_conta_nao_grava_nada(self, Cliente):
        Cliente.return_value = api_fox_simulada()
        with self.assertRaisesMessage(CadastroErro, 'não encontrado na conta FoxESS'):
            cadastrar_por_sn(Plataforma.FOXESS, 'SN-XYZ', self.cliente)
        self.assertFalse(Usina.objects.exists())

    def test_so_perfil_cliente_pode_ser_vinculado(self, Cliente):
        colaborador = Usuario.objects.create_user('col@x.com', 'x', nome='Col', perfil=Usuario.Perfil.COLABORADOR)
        with self.assertRaises(CadastroErro):
            cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', colaborador)
        Cliente.assert_not_called()                                          # nem chega a chamar a API



class FabricantePeloModeloTests(SimpleTestCase):
    def test_siw_e_weg(self):
        self.assertEqual(fabricante_pelo_modelo('SIW200G M050 W1'), Fabricante.WEG)
        self.assertEqual(fabricante_pelo_modelo('siw100g m010 w00'), Fabricante.WEG)

    def test_outros_sao_foxess(self):
        self.assertEqual(fabricante_pelo_modelo('T10-G3'), Fabricante.FOXESS)


@override_settings(FOXESS_API_KEY='CHAVE-TESTE')
@patch('integracoes.cadastro.FoxESSCliente')
class ReativacaoTests(TestCase):
    def test_cadastrar_sn_de_usina_apagada_reativa_com_historico(self, Cliente):
        from monitoramento.models import GeracaoDiaria
        from django.utils import timezone
        Cliente.return_value = api_fox_simulada()
        antigo = Usuario.objects.create_user('antigo@x.com', 'x', nome='Antigo')
        novo = Usuario.objects.create_user('novo@x.com', 'x', nome='Novo')

        cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', antigo)
        usina = Usina.objects.get()
        GeracaoDiaria.objects.create(usina=usina, data=timezone.localdate(), energia_kwh=99)
        usina.desativar()

        r = cadastrar_por_sn(Plataforma.FOXESS, 'SN-A', novo)

        usina.refresh_from_db()
        self.assertTrue(r.reativada)
        self.assertFalse(r.usina_nova)
        self.assertEqual(r.usina.pk, usina.pk)                            # a MESMA usina, não uma nova
        self.assertTrue(usina.ativa)
        self.assertIsNone(usina.desativada_em)
        self.assertEqual(list(usina.usuarios.all()), [novo])              # o antigo não volta sozinho
        self.assertEqual(float(GeracaoDiaria.objects.get(usina=usina).energia_kwh), 99.0)   # histórico de volta
