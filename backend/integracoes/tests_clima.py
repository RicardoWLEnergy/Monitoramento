"""Testes do clima do dia (Open-Meteo simulada no formato real; nenhuma chamada de verdade)."""
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from monitoramento.models import ClimaDiario, GeracaoDiaria
from usinas.models import Fabricante, Plataforma, Usina
from usuarios.models import Usuario

from . import clima


def resposta(dias, codigos, chuvas):
    r = MagicMock(status_code=200)
    r.json.return_value = {'latitude': -15.75, 'longitude': -47.75, 'timezone': 'America/Sao_Paulo',
                           'daily': {'time': dias, 'weather_code': codigos, 'precipitation_sum': chuvas}}
    return r


def criar_usina(nome, lat=-15.7801, lon=-47.9292):
    return Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.WEG, id_externo=nome,
                                nome=nome, latitude=lat, longitude=lon)


class ClassificacaoTests(TestCase):
    def test_codigos_e_chuva(self):
        self.assertEqual(clima.classificar(0, 0), 'ensolarado')
        self.assertEqual(clima.classificar(1, 0.2), 'ensolarado')
        self.assertEqual(clima.classificar(3, 0), 'nublado')
        self.assertEqual(clima.classificar(45, 0), 'nublado')           # neblina
        self.assertEqual(clima.classificar(61, 0.4), 'chuvoso')          # código de chuva
        self.assertEqual(clima.classificar(3, 5.0), 'chuvoso')           # nublado mas choveu 5 mm


@patch('integracoes.clima.requests.get')
class AtualizarClimaTests(TestCase):
    def test_grava_por_usina_arredonda_e_compartilha_a_consulta(self, get):
        hoje = timezone.localdate()
        a, b = criar_usina('A', -15.7801, -47.9292), criar_usina('B', -15.7799, -47.9301)   # mesma região
        criar_usina('Sem coordenadas', None, None)
        get.return_value = resposta([hoje.isoformat()], [63], [12.4])
        n = clima.atualizar_clima(Usina.objects.all(), hoje, hoje)
        self.assertEqual(n, 2)
        self.assertEqual(get.call_count, 1)                                   # 1 consulta para as duas
        self.assertEqual(get.call_args.kwargs['params']['latitude'], '-15.78')   # ~1 km, não o endereço exato
        c = ClimaDiario.objects.get(usina=a)
        self.assertEqual((c.condicao, c.chuva_mm), ('chuvoso', 12.4))
        self.assertTrue(ClimaDiario.objects.filter(usina=b).exists())

    def test_dias_antigos_usam_o_arquivo_e_recentes_a_previsao(self, get):
        hoje = timezone.localdate()
        criar_usina('A')
        get.side_effect = lambda url, params, timeout: resposta([params['start_date']], [0], [0])
        clima.atualizar_clima(Usina.objects.all(), hoje - timedelta(days=30), hoje)
        urls = [c.args[0] for c in get.call_args_list]
        self.assertTrue(any('archive' in u for u in urls))
        self.assertTrue(any('forecast' in u for u in urls))

    def test_falha_vira_clima_erro(self, get):
        criar_usina('A')
        get.return_value = MagicMock(status_code=429, json=MagicMock(return_value={'reason': 'limite'}))
        with self.assertRaisesMessage(clima.ClimaErro, '429'):
            clima.atualizar_clima(Usina.objects.all(), timezone.localdate(), timezone.localdate())

    def test_repetir_nao_duplica(self, get):
        hoje = timezone.localdate()
        criar_usina('A')
        get.return_value = resposta([hoje.isoformat()], [0], [0])
        clima.atualizar_clima(Usina.objects.all(), hoje, hoje)
        get.return_value = resposta([hoje.isoformat()], [80], [3])
        clima.atualizar_clima(Usina.objects.all(), hoje, hoje)
        self.assertEqual(ClimaDiario.objects.get().condicao, 'chuvoso')   # atualizado, não duplicado


@patch('integracoes.clima.requests.get')
class CidadeTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def busca(self, *resultados):
        return MagicMock(status_code=200, json=MagicMock(return_value={'results': list(resultados)}))

    def test_usa_a_cidade_do_estado_certo_e_guarda(self, get):
        get.return_value = self.busca(
            {'name': 'Planaltina', 'latitude': -15.45, 'longitude': -47.61, 'admin1': 'Distrito Federal'},
            {'name': 'Planaltina', 'latitude': -15.21, 'longitude': -47.65, 'admin1': 'Goiás'})
        self.assertEqual(clima.coordenadas_da_cidade('Planaltina', 'GO'), (-15.21, -47.65))
        self.assertEqual(clima.coordenadas_da_cidade('planaltina', 'go'), (-15.21, -47.65))
        self.assertEqual(get.call_count, 1)                                # 2ª vez: guardado

    def test_usina_sem_coordenadas_usa_a_cidade_sem_gravar_na_usina(self, get):
        hoje = timezone.localdate()
        usina = Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.WEG, id_externo='F',
                                     nome='Fox', cidade='Brasilia', uf='DF')
        get.side_effect = [
            self.busca({'name': 'Brasília', 'latitude': -15.7797, 'longitude': -47.9297, 'admin1': 'Distrito Federal'}),
            resposta([hoje.isoformat()], [0], [0]),
        ]
        self.assertEqual(clima.atualizar_clima(Usina.objects.all(), hoje, hoje), 1)
        self.assertEqual(ClimaDiario.objects.get(usina=usina).condicao, 'ensolarado')
        usina.refresh_from_db()
        self.assertIsNone(usina.latitude)                                  # não grava a cidade como endereço

    def test_cidade_nao_encontrada_fica_de_fora(self, get):
        get.return_value = self.busca()
        Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.WEG, id_externo='F',
                             nome='Fox', cidade='Lugar Inexistente')
        self.assertEqual(clima.atualizar_clima(Usina.objects.all(), timezone.localdate(), timezone.localdate()), 0)


class ClimaApiTests(APITestCase):
    def test_clima_no_grafico_do_dia_e_nas_barras(self):
        hoje = timezone.localdate()
        usina = criar_usina('A')
        admin = Usuario.objects.create_user('a@x.com', 'x', nome='A', perfil='admin')
        ClimaDiario.objects.create(usina=usina, data=hoje, condicao='nublado', chuva_mm=0.4)
        GeracaoDiaria.objects.create(usina=usina, data=hoje, energia_kwh=10)
        self.client.force_authenticate(admin)
        r = self.client.get(f'/api/usinas/{usina.pk}/curva/?data={hoje}')
        self.assertEqual(r.data['clima'], {'condicao': 'nublado', 'chuva_mm': 0.4})
        r = self.client.get(f'/api/usinas/{usina.pk}/geracao-diaria/?inicio={hoje - timedelta(days=1)}&fim={hoje}')
        self.assertEqual([d['clima'] for d in r.data['dias']], [None, {'condicao': 'nublado', 'chuva_mm': 0.4}])


class ClimaNaoTravaTests(TestCase):
    @patch('integracoes.clima.requests.get')
    def test_busca_de_cidade_desiste_na_primeira_falha(self, get):
        import requests as req
        from django.core.cache import cache
        cache.clear()
        get.side_effect = req.Timeout('lento')
        for i in range(5):
            Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.WEG, id_externo=f'F{i}',
                                 nome=f'Fox {i}', cidade=f'Cidade {i}')
        with self.assertLogs('coletor', level='WARNING'):
            self.assertEqual(clima.atualizar_clima(Usina.objects.all(), timezone.localdate(), timezone.localdate()), 0)
        self.assertEqual(get.call_count, 1)          # não esperou 5 × o tempo-limite

    @patch('integracoes.clima.requests.get')
    def test_prazo_da_rodada_esgotado_para_sem_erro(self, get):
        criar_usina('A')
        with self.assertLogs('coletor', level='WARNING'):
            self.assertEqual(clima.atualizar_clima(Usina.objects.all(), timezone.localdate(),
                                                   timezone.localdate(), segundos=-1), 0)
        get.assert_not_called()


class ColetorClimaTests(TestCase):
    @patch('integracoes.coletor.clima.atualizar_clima', side_effect=clima.ClimaErro('fora do ar'))
    def test_falha_do_clima_nao_para_o_coletor_e_espera_3_horas(self, atualizar):
        from .coletor import atualizar_clima_recente
        with self.assertLogs('coletor', level='WARNING'):
            atualizar_clima_recente(forcar=True)
        atualizar_clima_recente()                       # menos de 3 h depois: não consulta de novo
        self.assertEqual(atualizar.call_count, 1)

    @patch('integracoes.coletor.clima.atualizar_clima', side_effect=RuntimeError('banco caiu'))
    def test_qualquer_erro_do_clima_so_vai_para_o_log(self, atualizar):
        from .coletor import atualizar_clima_recente
        with self.assertLogs('coletor', level='ERROR'):
            atualizar_clima_recente(forcar=True)        # não levanta exceção
