"""Testes do cliente Huawei FusionSolar (sem rede: respostas simuladas)."""
from datetime import datetime, timezone as tz
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from .huawei import HuaweiCliente, HuaweiErro, em_lotes, ms


def resposta(json_data, cabecalhos=None):
    r = MagicMock(content=b'{}', headers=cabecalhos or {}, cookies={})
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


LOGIN_OK = resposta({'success': True, 'failCode': 0}, {'xsrf-token': 'TOKEN-1'})


class HuaweiClienteTests(SimpleTestCase):
    def setUp(self):
        self.api = HuaweiCliente('https://la5.fusionsolar.huawei.com/thirdData/', 'usuario', 'senha')
        self.api.INTERVALO_POR_ENDPOINT = 0

    def test_sem_credenciais_avisa(self):
        with self.assertRaises(ValueError):
            HuaweiCliente('https://x/thirdData', '', '')

    def test_login_guarda_token_no_cabecalho(self):
        with patch.object(self.api.sessao, 'post', return_value=LOGIN_OK) as post:
            self.api.login()
        self.assertEqual(self.api.sessao.headers['XSRF-TOKEN'], 'TOKEN-1')
        url, = post.call_args.args
        self.assertEqual(url, 'https://la5.fusionsolar.huawei.com/thirdData/login')
        self.assertEqual(post.call_args.kwargs['json'], {'userName': 'usuario', 'systemCode': 'senha'})

    def test_login_recusado(self):
        with patch.object(self.api.sessao, 'post', return_value=resposta({'success': False, 'failCode': 20001})):
            with self.assertRaises(HuaweiErro):
                self.api.login()

    def test_primeira_chamada_faz_login_e_reaproveita_token(self):
        dados = resposta({'success': True, 'failCode': 0, 'data': []})
        with patch.object(self.api.sessao, 'post', side_effect=[LOGIN_OK, dados, dados]) as post:
            self.api.chamar('getStationRealKpi', {})
            self.api.chamar('getStationRealKpi', {})
        self.assertEqual(post.call_count, 3)   # 1 login + 2 chamadas (sem relogar)

    def test_sessao_expirada_reloga_e_repete(self):
        expirada = resposta({'success': False, 'failCode': 305})
        ok = resposta({'success': True, 'failCode': 0, 'data': ['ok']})
        login2 = resposta({'success': True, 'failCode': 0}, {'xsrf-token': 'TOKEN-2'})
        with patch.object(self.api.sessao, 'post', side_effect=[LOGIN_OK, expirada, login2, ok]):
            self.assertEqual(self.api.chamar('getDevList', {}), ['ok'])
        self.assertEqual(self.api.sessao.headers['XSRF-TOKEN'], 'TOKEN-2')

    def test_limite_de_frequencia(self):
        with patch.object(self.api.sessao, 'post', side_effect=[LOGIN_OK, resposta({'success': False, 'failCode': 407})]):
            with self.assertRaises(HuaweiErro) as ctx:
                self.api.chamar('getDevRealKpi', {})
        self.assertTrue(ctx.exception.e_limite)

    def test_paginacao_de_usinas(self):
        paginas = [
            LOGIN_OK,
            resposta({'success': True, 'failCode': 0, 'data': {'list': [{'plantCode': f'NE={i}'} for i in range(100)], 'pageCount': 2}}),
            resposta({'success': True, 'failCode': 0, 'data': {'list': [{'plantCode': 'NE=X'}], 'pageCount': 2}}),
        ]
        with patch.object(self.api.sessao, 'post', side_effect=paginas) as post:
            self.assertEqual(len(self.api.listar_usinas()), 101)
        self.assertEqual(post.call_args_list[2].kwargs['json'], {'pageNo': 2, 'pageSize': 100})

    def test_historico_em_lotes_de_10_dispositivos(self):
        vazio = resposta({'success': True, 'failCode': 0, 'data': []})
        with patch.object(self.api.sessao, 'post', side_effect=[LOGIN_OK] + [vazio] * 3) as post:
            self.api.historico_dispositivos(list(range(25)), 1, datetime(2026, 11, 9, tzinfo=tz.utc),
                                            datetime(2026, 11, 10, tzinfo=tz.utc))
        lotes = [len(c.kwargs['json']['devIds'].split(',')) for c in post.call_args_list[1:]]
        self.assertEqual(lotes, [10, 10, 5])
        self.assertEqual(post.call_args_list[1].kwargs['json']['startTime'], 1794182400000)   # 09/11/2026 00:00 UTC


class AuxiliaresTests(SimpleTestCase):
    def test_em_lotes(self):
        self.assertEqual([len(l) for l in em_lotes(list(range(250)), 100)], [100, 100, 50])

    def test_ms(self):
        self.assertEqual(ms(datetime(2026, 1, 1, tzinfo=tz.utc)), 1767225600000)
