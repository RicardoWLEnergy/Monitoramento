"""
Cadastro e coleta Huawei com respostas simuladas no formato REAL da API
(copiado do teste com a conta da WL — usina "Diogo e Neide", inversor SUN2000L-3KTL).
"""
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from monitoramento.models import GeracaoDiaria, Leitura
from usinas.models import Fabricante, Inversor, Plataforma, Status, Usina
from usuarios.models import Usuario

from . import coleta_huawei
from .cadastro import CadastroErro, cadastrar_por_sn, potencia_pelo_modelo_huawei
from .huawei import HuaweiErro

SP = ZoneInfo('America/Sao_Paulo')

USINAS = [
    {'plantCode': 'NE=33628081', 'plantName': 'Usina Diogo e Neide', 'capacity': 3.0,
     'latitude': '-15.617980', 'longitude': '-47.771750',
     'plantAddress': 'Condominio alto da boa vista  QD103 CONJUNTO 04 LT 37'},
    {'plantCode': 'NE=1', 'plantName': 'Outra', 'capacity': 5.0},
]
DISPOSITIVOS = [
    {'id': 1000000033629201, 'esnCode': '210107380110JB000260', 'devTypeId': 38,
     'invType': 'SUN2000L-3KTL', 'stationCode': 'NE=33628081'},
    {'id': 555, 'esnCode': 'DONGLE-1', 'devTypeId': 62, 'stationCode': 'NE=33628081'},   # não é inversor
    {'id': 999, 'esnCode': 'OUTRO-INV', 'devTypeId': 1, 'invType': 'SUN2000-17KTL', 'stationCode': 'NE=1'},
]


def api_simulada():
    api = MagicMock()
    api.listar_usinas.return_value = USINAS
    api.listar_dispositivos.return_value = DISPOSITIVOS
    api.tempo_real_usinas.return_value = [{'stationCode': 'NE=33628081', 'dataItemMap': {'real_health_state': 3}}]
    return api


class PotenciaPeloModeloTests(SimpleTestCase):
    def test_extrai_kw_do_modelo(self):
        self.assertEqual(potencia_pelo_modelo_huawei('SUN2000L-3KTL'), Decimal('3.00'))
        self.assertEqual(potencia_pelo_modelo_huawei('SUN2000-17KTL-M0'), Decimal('17.00'))
        self.assertEqual(potencia_pelo_modelo_huawei('SUN2000-4.6KTL-L1'), Decimal('4.60'))
        self.assertEqual(potencia_pelo_modelo_huawei(''), Decimal('0'))


@override_settings(HUAWEI_USUARIO='u', HUAWEI_SENHA='s')
@patch('integracoes.cadastro.HuaweiCliente')
class CadastroHuaweiTests(TestCase):
    def setUp(self):
        self.cliente = Usuario.objects.create_user('cli@x.com', 'x', nome='Cliente')

    def test_cadastra_pela_sn(self, Cliente):
        Cliente.return_value = api_simulada()
        r = cadastrar_por_sn(Plataforma.HUAWEI, '210107380110jb000260', self.cliente)

        u = Usina.objects.get()
        self.assertTrue(r.usina_nova)
        self.assertEqual((u.plataforma, u.id_externo, u.fabricante), (Plataforma.HUAWEI, 'NE=33628081', Fabricante.HUAWEI))
        self.assertEqual((u.nome, str(u.potencia_kwp), u.status), ('Usina Diogo e Neide', '3.00', Status.ONLINE))
        self.assertEqual((str(u.latitude), str(u.longitude)), ('-15.617980', '-47.771750'))
        inv = Inversor.objects.get()                                   # só o inversor (o dongle fica de fora)
        self.assertEqual((inv.numero_serie, inv.id_externo, inv.tipo_externo, inv.modelo),
                         ('210107380110JB000260', '1000000033629201', '38', 'SUN2000L-3KTL'))
        self.assertEqual(str(inv.potencia_nominal_kw), '3.00')
        self.assertEqual(list(self.cliente.usinas.all()), [u])

    def test_sn_inexistente(self, Cliente):
        Cliente.return_value = api_simulada()
        with self.assertRaisesMessage(CadastroErro, 'não encontrado na conta Huawei'):
            cadastrar_por_sn(Plataforma.HUAWEI, 'NAO-EXISTE', self.cliente)
        self.assertFalse(Usina.objects.exists())

    def test_sn_que_nao_e_inversor(self, Cliente):
        Cliente.return_value = api_simulada()
        with self.assertRaisesMessage(CadastroErro, 'não é de um inversor'):
            cadastrar_por_sn(Plataforma.HUAWEI, 'DONGLE-1', self.cliente)

    def test_erro_da_api_vira_mensagem(self, Cliente):
        api = api_simulada()
        api.listar_usinas.side_effect = HuaweiErro('stations', 407)
        Cliente.return_value = api
        with self.assertRaisesMessage(CadastroErro, 'Falha ao consultar a Huawei'):
            cadastrar_por_sn(Plataforma.HUAWEI, '210107380110JB000260', self.cliente)


class ColetaHuaweiBase(TestCase):
    def setUp(self):
        self.usina = Usina.objects.create(plataforma=Plataforma.HUAWEI, fabricante=Fabricante.HUAWEI,
                                          id_externo='NE=33628081', nome='Usina Diogo e Neide', potencia_kwp=3)
        self.inv = Inversor.objects.create(usina=self.usina, numero_serie='210107380110JB000260',
                                           id_externo='1000000033629201', tipo_externo='38')
        self.api = MagicMock()


class TempoRealHuaweiTests(ColetaHuaweiBase):
    def tempo_real(self, potencia, estado, comunicando=1):
        return [{'devId': 1000000033629201, 'sn': '210107380110JB000260', 'dataItemMap': {
            'active_power': potencia, 'day_cap': 11.9, 'inverter_state': float(estado), 'run_state': comunicando}}]

    def test_gerando(self):
        self.api.tempo_real_dispositivos.return_value = self.tempo_real(2.1, 512)
        coleta_huawei.atualizar_tempo_real(api=self.api)
        self.api.tempo_real_dispositivos.assert_called_once_with(['1000000033629201'], 38)
        self.inv.refresh_from_db()
        self.usina.refresh_from_db()
        self.assertEqual((self.inv.status, float(self.inv.potencia_atual_kw)), (Status.ONLINE, 2.1))
        self.assertEqual(self.usina.status, Status.ONLINE)
        self.assertIsNotNone(self.usina.ultima_leitura)
        self.assertEqual(Leitura.objects.get().potencia_kw, 2.1)
        self.assertEqual(float(GeracaoDiaria.objects.get().energia_kwh), 11.9)

    def test_noite_standby_fica_offline(self):
        self.api.tempo_real_dispositivos.return_value = self.tempo_real(0.0, 40960)   # formato real (noite)
        coleta_huawei.atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()
        self.assertEqual(self.usina.status, Status.OFFLINE)

    def test_falha_vira_alerta(self):
        self.api.tempo_real_dispositivos.return_value = self.tempo_real(0.0, 768)
        coleta_huawei.atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()
        self.assertEqual(self.usina.status, Status.ALERTA)

    def test_sem_comunicacao_nao_grava_leitura(self):
        self.api.tempo_real_dispositivos.return_value = self.tempo_real(0.0, 45056, comunicando=0)
        coleta_huawei.atualizar_tempo_real(api=self.api)
        self.assertFalse(Leitura.objects.exists())

    def test_ignora_usinas_foxess(self):
        Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.WEG, id_externo='fx', nome='Fox')
        self.api.tempo_real_dispositivos.return_value = self.tempo_real(1.0, 512)
        rel = coleta_huawei.atualizar_tempo_real(api=self.api)
        self.assertEqual(rel.inversores, 1)


class GeracaoDiariaHuaweiTests(ColetaHuaweiBase):
    def test_um_registro_por_dia_no_fuso_da_usina(self):
        hoje = timezone.localdate()
        inicio_mes = datetime(hoje.year, hoje.month, 1, tzinfo=SP)
        # formato real: collectTime = meia-noite local do dia, em ms
        self.api.kpi_diario.return_value = [
            {'collectTime': int((inicio_mes + timedelta(days=i)).timestamp() * 1000), 'stationCode': 'NE=33628081',
             'dataItemMap': {'inverter_power': 10.0 + i, 'PVYield': 10.0 + i}}
            for i in range(hoje.day)
        ]
        rel = coleta_huawei.importar_geracao_diaria(self.usina, hoje.replace(day=1), hoje, api=self.api)
        self.assertEqual(rel.dias, hoje.day)
        self.assertEqual(float(GeracaoDiaria.objects.get(data=hoje.replace(day=1)).energia_kwh), 10.0)
        self.assertEqual(self.api.kpi_diario.call_count, 1)   # 1 chamada por mês


class CurvasHuaweiTests(ColetaHuaweiBase):
    def test_soma_por_bloco_de_5_min_em_janelas_de_3_dias(self):
        hoje = timezone.localdate()
        dez_horas = datetime(hoje.year, hoje.month, hoje.day, 10, 0, 40, tzinfo=SP)
        self.api.historico_dispositivos.return_value = [
            {'devId': 1000000033629201, 'collectTime': int(dez_horas.timestamp() * 1000),
             'dataItemMap': {'active_power': 1.5}},
        ]
        rel = coleta_huawei.importar_curvas(self.usina, hoje - timedelta(days=4), hoje, api=self.api)
        self.assertEqual(self.api.historico_dispositivos.call_count, 2)   # 5 dias = 2 janelas (3 + 2)
        self.assertEqual(Leitura.objects.get().data_hora, dez_horas.replace(second=0))
        self.assertEqual(rel.leituras, 1)

    def test_interface_nao_liberada_avisa_como_resolver(self):
        hoje = timezone.localdate()
        self.api.historico_dispositivos.side_effect = HuaweiErro('getDevHistoryKpi', 401)
        rel = coleta_huawei.importar_curvas(self.usina, hoje, hoje, api=self.api)
        self.assertIn('não liberada na conta Northbound', rel.falhas[0])
        self.assertFalse(Leitura.objects.exists())
