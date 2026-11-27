"""
Sungrow iSolarCloud (modo usuário): cliente (login/token), cadastro por SN e coleta.
Sem rede: respostas simuladas no formato da documentação da OpenAPI.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from monitoramento.models import GeracaoDiaria, Leitura
from usinas.models import Fabricante, Inversor, Plataforma, Status, Usina
from usuarios.models import Usuario

from . import coleta_sungrow
from .cadastro import CadastroErro, cadastrar_por_sn, data_conexao_sungrow, potencia_pelo_modelo_sungrow
from .coleta_sungrow import em_k, fuso_sungrow
from .coletor import Clientes, ciclo_tempo_real
from .sungrow import CHAVE_LOGIN_SUSPENSO, SungrowCliente, SungrowErro, SungrowLimiteErro, SungrowLoginErro

SP = ZoneInfo('America/Sao_Paulo')
CHAVES = dict(SUNGROW_APPKEY='APPKEY', SUNGROW_ACCESS_KEY='ACCESS', SUNGROW_USUARIO='conta@exemplo.com',
              SUNGROW_SENHA='senha', SUNGROW_API_URL='https://gateway.exemplo')


def resposta(json_data, status=200):
    r = MagicMock(status_code=status)
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


def ok(dados):
    return resposta({'req_serial_num': 'x', 'result_code': '1', 'result_msg': 'success', 'result_data': dados})


LOGIN_OK = ok({'login_state': '1', 'token': '503093_fce7a5839e6c46f998952d55c0384774', 'user_id': '503093'})
TOKEN_VENCIDO = resposta({'result_code': 'E00003', 'result_msg': 'er_token_login_invalid', 'result_data': None})


# ----------------------------------------------------------------------------
# Cliente: login e token
# ----------------------------------------------------------------------------
@override_settings(**CHAVES)
class SungrowClienteTests(TestCase):
    def setUp(self):
        cache.delete(CHAVE_LOGIN_SUSPENSO)
        self.api = SungrowCliente()
        self.api.INTERVALO_POR_ENDPOINT = 0

    def test_sem_credenciais_avisa(self):
        with self.assertRaises(ValueError):
            SungrowCliente(usuario='', senha='')

    def test_login_e_chamada_levam_chaves_e_token_no_corpo(self):
        with patch.object(self.api.sessao, 'post', side_effect=[LOGIN_OK, ok({'ps_id': 1})]) as post:
            self.api.detalhe_usina_por_sn('A2400000001')
        self.assertEqual((self.api.sessao.headers['sys_code'], self.api.sessao.headers['x-access-key']), ('901', 'ACCESS'))
        self.assertNotIn('Authorization', self.api.sessao.headers)
        login, chamada = post.call_args_list
        self.assertTrue(login.args[0].endswith('/openapi/login'))
        self.assertEqual(login.kwargs['json'], {'appkey': 'APPKEY', 'lang': '_pt_BR',
                                                'user_account': 'conta@exemplo.com', 'user_password': 'senha'})
        self.assertTrue(chamada.args[0].endswith('/openapi/getPowerStationDetail'))
        self.assertEqual(chamada.kwargs['json']['token'], '503093_fce7a5839e6c46f998952d55c0384774')
        self.assertEqual(chamada.kwargs['json']['sn'], 'A2400000001')

    def test_reaproveita_o_token(self):
        with patch.object(self.api.sessao, 'post', side_effect=[LOGIN_OK, ok({}), ok({})]) as post:
            self.api.detalhe_usina_por_sn('A')
            self.api.detalhe_usina_por_sn('B')
        self.assertEqual(post.call_count, 3)      # 1 login só

    def test_token_vencido_faz_login_de_novo_e_repete_uma_vez(self):
        with patch.object(self.api.sessao, 'post',
                          side_effect=[LOGIN_OK, TOKEN_VENCIDO, LOGIN_OK, ok({'ps_id': 7})]) as post:
            self.assertEqual(self.api.detalhe_usina_por_sn('A'), {'ps_id': 7})
        self.assertEqual(post.call_count, 4)

    def test_login_recusado_nao_insiste(self):
        # result_code "1" mesmo com senha errada: o que vale é login_state
        recusado = ok({'login_state': '0', 'msg': 'senha incorreta'})
        with patch.object(self.api.sessao, 'post', return_value=recusado) as post:
            with self.assertRaisesMessage(SungrowLoginErro, 'senha incorreta'):
                self.api.detalhe_usina_por_sn('A')
            with self.assertRaisesMessage(SungrowLoginErro, 'suspenso'):
                SungrowCliente().detalhe_usina_por_sn('A')      # outro cliente (ex.: a tela) também não tenta
        self.assertEqual(post.call_count, 1)

    def test_limite_de_chamadas(self):
        with patch.object(self.api.sessao, 'post',
                          side_effect=[LOGIN_OK, resposta({'result_code': 'E999', 'result_msg': 'hour limit'})]), \
                self.assertRaises(SungrowLimiteErro):
            self.api.detalhe_usina_por_sn('A')

    def test_paginacao_dos_dispositivos(self):
        self.api.TAMANHO_LOTE = 2
        paginas = [LOGIN_OK, ok({'rowCount': 3, 'pageList': [{'ps_key': 'a'}, {'ps_key': 'b'}]}),
                   ok({'rowCount': 3, 'pageList': [{'ps_key': 'c'}]})]
        with patch.object(self.api.sessao, 'post', side_effect=paginas) as post:
            self.assertEqual(len(self.api.dispositivos_da_usina(1)), 3)
        self.assertEqual(post.call_args_list[2].kwargs['json']['curPage'], 2)


class AuxiliaresSungrowTests(SimpleTestCase):
    def test_fuso(self):
        self.assertEqual(fuso_sungrow('GMT-3'), 'America/Sao_Paulo')
        self.assertEqual(fuso_sungrow('GMT-4'), 'America/Manaus')
        self.assertEqual(fuso_sungrow('GMT+1'), 'Etc/GMT-1')
        self.assertEqual(fuso_sungrow(''), 'America/Sao_Paulo')

    def test_unidades(self):
        self.assertEqual(em_k('5000'), 5.0)
        self.assertEqual(em_k('84300.0'), 84.3)
        self.assertEqual(em_k('--'), 0.0)

    def test_potencia_pelo_modelo(self):
        self.assertEqual(potencia_pelo_modelo_sungrow('SG10RT'), Decimal('10.00'))
        self.assertEqual(potencia_pelo_modelo_sungrow('SG5.0RS'), Decimal('5.00'))
        self.assertEqual(potencia_pelo_modelo_sungrow('SG110CX'), Decimal('110.00'))
        self.assertEqual(potencia_pelo_modelo_sungrow('SH10RT'), Decimal('10.00'))
        self.assertEqual(potencia_pelo_modelo_sungrow(''), Decimal('0'))

    def test_data_de_conexao(self):
        self.assertEqual(data_conexao_sungrow(20230303115625), date(2023, 3, 3))
        self.assertEqual(data_conexao_sungrow('2022-11-07 15:37:40'), date(2022, 11, 7))
        self.assertIsNone(data_conexao_sungrow(''))


# ----------------------------------------------------------------------------
# Cadastro pela SN
# ----------------------------------------------------------------------------
DETALHE = {'ps_id': 974621, 'ps_key': '974621_11_0_0', 'ps_name': 'Usina Exemplo ', 'ps_type': 4,
           'ps_location': 'Brasília - DF', 'latitude': -15.79, 'longitude': -47.88, 'design_capacity': 11000.0,
           'install_date': '2022-11-07 15:37:40', 'ps_current_time_zone': 'GMT-3',
           'communication_dev_detail_list': [{'is_enable': 1, 'sn': 'B2300000001'}]}
DISPOSITIVOS = [
    {'ps_id': 974621, 'ps_key': '974621_1_10_1', 'device_sn': 'A2400000001', 'device_type': 1,
     'device_model_code': 'SG10RT', 'dev_fault_status': 4, 'dev_status': '1'},
    {'ps_id': 974621, 'ps_key': '974621_1_11_1', 'device_sn': 'A2400000002', 'device_type': 1,
     'device_model_code': 'SG5.0RS', 'dev_fault_status': 1, 'dev_status': '1'},
]


@override_settings(**CHAVES)
@patch('integracoes.cadastro.SungrowCliente')
class CadastroSungrowTests(TestCase):
    def setUp(self):
        self.cliente = Usuario.objects.create_user('cli@x.com', 'x', nome='Cliente')

    def api(self):
        api = MagicMock()
        api.detalhe_usina_por_sn.return_value = DETALHE
        api.dispositivos_da_usina.return_value = DISPOSITIVOS
        return api

    def test_cadastra_pela_sn(self, Cliente):
        Cliente.return_value = api = self.api()
        r = cadastrar_por_sn(Plataforma.SUNGROW, 'a2400000001', self.cliente)

        u = Usina.objects.get()
        self.assertTrue(r.usina_nova)
        self.assertEqual((u.plataforma, u.id_externo, u.fabricante), (Plataforma.SUNGROW, '974621', Fabricante.SUNGROW))
        self.assertEqual((u.nome, str(u.potencia_kwp), u.fuso_horario), ('Usina Exemplo', '11.00', 'America/Sao_Paulo'))
        self.assertEqual((str(u.latitude), u.inicio_operacao), ('-15.790000', date(2022, 11, 7)))
        self.assertEqual(u.status, Status.ALERTA)              # o 2º inversor está em falha
        inv = Inversor.objects.get(numero_serie='A2400000001')
        self.assertEqual((inv.id_externo, inv.tipo_externo, inv.modelo, inv.potencia_nominal_kw),
                         ('974621_1_10_1', '1', 'SG10RT', Decimal('10.00')))
        self.assertEqual(Inversor.objects.count(), 2)
        api.detalhe_usina_por_sn.assert_called_once_with('A2400000001')
        self.assertTrue(u.usuarios.filter(pk=self.cliente.pk).exists())

    def test_sem_detalhe_pela_sn_procura_no_tempo_real(self, Cliente):
        Cliente.return_value = api = self.api()
        api.detalhe_usina_por_sn.side_effect = SungrowErro('getPowerStationDetail', '010')
        api.tempo_real_dispositivos.side_effect = lambda tipo, pontos, sns: (
            [{'device_sn': sns[0], 'ps_id': 974621}] if tipo == 14 else [])   # inversor híbrido
        api.detalhe_usinas.return_value = [{**DETALHE, 'design_capacity': None, 'install_power': 11000}]
        cadastrar_por_sn(Plataforma.SUNGROW, 'A2400000001', self.cliente)
        api.detalhe_usinas.assert_called_once_with([974621])
        self.assertEqual(str(Usina.objects.get().potencia_kwp), '11.00')

    def test_sn_desconhecida(self, Cliente):
        Cliente.return_value = api = self.api()
        api.detalhe_usina_por_sn.return_value = {}
        api.tempo_real_dispositivos.return_value = []
        with self.assertRaisesMessage(CadastroErro, 'não encontrado na conta Sungrow'):
            cadastrar_por_sn(Plataforma.SUNGROW, 'X1', self.cliente)
        self.assertFalse(Usina.objects.exists())

    def test_login_recusado(self, Cliente):
        Cliente.return_value = api = self.api()
        api.detalhe_usina_por_sn.side_effect = SungrowLoginErro('0')
        with self.assertRaisesMessage(CadastroErro, 'Confira o usuário e a senha da Sungrow'):
            cadastrar_por_sn(Plataforma.SUNGROW, 'A2400000001', self.cliente)
        api.tempo_real_dispositivos.assert_not_called()       # não insiste


# ----------------------------------------------------------------------------
# Coleta
# ----------------------------------------------------------------------------
class ColetaSungrowBase(TestCase):
    def setUp(self):
        self.usina = Usina.objects.create(plataforma=Plataforma.SUNGROW, fabricante=Fabricante.SUNGROW,
                                          id_externo='974621', nome='Usina Exemplo')
        self.inv = Inversor.objects.create(usina=self.usina, numero_serie='A2400000001',
                                           id_externo='974621_1_10_1', tipo_externo='1')
        self.api = MagicMock()


class TempoRealSungrowTests(ColetaSungrowBase):
    def coletar_as(self, hora, potencia_w, estado, falha=4, atraso_min=3):
        agora = datetime.combine(timezone.localdate(), datetime.min.time(), SP).replace(hour=hora)
        leitura = agora - timedelta(minutes=atraso_min)
        self.api.tempo_real_dispositivos.return_value = [{
            'ps_key': '974621_1_10_1', 'device_sn': 'A2400000001', 'ps_id': 974621,
            'device_time': leitura.strftime('%Y%m%d%H%M%S'), 'dev_status': 1, 'dev_fault_status': falha,
            'p24': str(potencia_w), 'p1': '84300.0', 'p29': str(estado)}]
        with patch('integracoes.coleta_sungrow.timezone.now', return_value=agora):
            rel = coleta_sungrow.atualizar_tempo_real(api=self.api)
        self.inv.refresh_from_db()
        return rel

    def test_gerando_converte_unidades_e_grava_curva_e_energia(self):
        self.coletar_as(11, 5000, 64)
        self.assertEqual((self.inv.potencia_atual_kw, self.inv.geracao_hoje_kwh), (Decimal('5.000'), Decimal('84.300')))
        self.assertEqual(self.inv.status, Status.ONLINE)
        self.assertEqual(Leitura.objects.get().potencia_kw, 5.0)
        self.assertEqual(float(GeracaoDiaria.objects.get().energia_kwh), 84.3)
        self.api.tempo_real_dispositivos.assert_called_once_with(1, ['24', '1', '29'], ps_keys=['974621_1_10_1'])

    def test_falha_vira_alerta(self):
        self.coletar_as(11, 0, 21760)
        self.assertEqual(self.inv.status, Status.ALERTA)
        self.coletar_as(11, 3000, 64, falha=1)          # gerando, mas a Sungrow aponta falha
        self.assertEqual(self.inv.status, Status.ALERTA)

    def test_sem_gerar_em_pleno_dia_e_alerta_e_com_pouco_sol_e_sem_sol(self):
        self.coletar_as(11, 0, 5120)                     # standby em pleno dia
        self.assertEqual(self.inv.status, Status.ALERTA)
        self.coletar_as(7, 0, 5120)
        self.assertEqual(self.inv.status, Status.NOITE)

    def test_leitura_velha_e_offline(self):
        self.coletar_as(11, 5000, 64, atraso_min=180)
        self.assertEqual(self.inv.status, Status.OFFLINE)
        self.assertFalse(Leitura.objects.exists())

    def test_limite_de_chamadas_sobe_para_o_coletor(self):
        self.api.tempo_real_dispositivos.side_effect = SungrowLimiteErro('getDeviceRealTimeData', 'E999')
        with self.assertRaises(SungrowLimiteErro):
            coleta_sungrow.atualizar_tempo_real(api=self.api)


class HistoricoSungrowTests(ColetaSungrowBase):
    def test_energia_diaria_pela_usina_sem_pedir_hoje(self):
        hoje = timezone.localdate()
        ontem, anteontem = hoje - timedelta(days=1), hoje - timedelta(days=2)
        self.api.historico_diario.return_value = {
            '974621_11_0_0': {'p83022': [{'2': '30500.0', 'time_stamp': f'{anteontem:%Y%m%d}'},
                                         {'2': '28100.0', 'time_stamp': f'{ontem:%Y%m%d}'}]}}
        rel = coleta_sungrow.importar_geracao_diaria(self.usina, anteontem, hoje, api=self.api)
        self.assertEqual(rel.dias, 2)
        self.assertEqual(float(GeracaoDiaria.objects.get(data=ontem).energia_kwh), 28.1)
        self.api.historico_diario.assert_called_once_with(['974621_11_0_0'], '83022', anteontem, ontem)

    def test_so_hoje_nao_chama_a_sungrow(self):
        hoje = timezone.localdate()
        coleta_sungrow.importar_geracao_diaria(self.usina, hoje, hoje, api=self.api)
        self.api.historico_diario.assert_not_called()

    def test_curva_em_5_janelas_de_3_horas(self):
        ontem = timezone.localdate() - timedelta(days=1)
        dez = datetime(ontem.year, ontem.month, ontem.day, 10, 0, tzinfo=SP)
        self.api.historico_minuto.return_value = {'974621_11_0_0': [
            {'time_stamp': dez.strftime('%Y%m%d%H%M%S'), 'p83033': '4200.0'},
            {'time_stamp': (dez + timedelta(minutes=5)).strftime('%Y%m%d%H%M%S'), 'p83033': '--'},
        ]}
        rel = coleta_sungrow.importar_curvas(self.usina, ontem, ontem, api=self.api)
        self.assertEqual(self.api.historico_minuto.call_count, 5)
        primeira = self.api.historico_minuto.call_args_list[0].args
        self.assertEqual((primeira[0], primeira[2].hour, primeira[3].hour), (['974621_11_0_0'], 5, 8))
        self.assertEqual(Leitura.objects.get().potencia_kw, 4.2)
        self.assertEqual(rel.dias, 1)


class ColetorSungrowTests(ColetaSungrowBase):
    def test_login_recusado_nao_derruba_o_ciclo(self):
        clientes = Clientes()
        clientes._sungrow = self.api
        self.api.tempo_real_dispositivos.side_effect = SungrowLoginErro('0')
        resumo = ciclo_tempo_real(clientes)
        self.assertEqual(len(resumo.erros), 1)
        self.assertIn('senha incorreta', resumo.erros[0])
