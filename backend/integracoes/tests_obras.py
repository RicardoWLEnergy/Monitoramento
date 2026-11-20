"""Testes do projeto do cliente (planilha OBRAS simulada no formato real; nenhum acesso ao Google)."""
from datetime import date
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase

from usuarios.models import Usuario

from . import google, obras

CABECALHO = ['Nº OBRA', 'CLIENTE', 'TIPO', 'kWp', 'CIDADE', 'UF', 'DISTRIBUIDORA', 'FECHAMENTO', 'VENDEDOR',
             'FORMA DE PAGAMENTO', 'VALOR', 'INVERSOR', 'MÓDULOS', 'ETAPA ENGENHARIA', 'DOCUMENTAÇÃO',
             'HOMOLOGAÇÃO (ENTRADA)', 'APROVAÇÃO DO PROJETO', 'PROTOCOLO DISTRIBUIDORA', 'PROJETO',
             'INSTALAÇÃO (ENTRADA)', 'COMISSIONAMENTO', 'PROTOCOLO VISTORIA', 'VISTORIA TÉCNICA', 'PEDIDO WEG',
             'SITUAÇÃO', 'DIAS ATÉ HOMOLOGAR', 'DIAS ATÉ INSTALAR', 'DATA FATURAMENTO', 'NOTA FISCAL',
             'CHEGADA NA SEDE', 'INSTALAÇÃO PROGRAMADA', 'INSTALAÇÃO CONCLUÍDA', 'ID PIPEDRIVE', 'ID ENGENHARIA',
             'ID ART', 'ID PARECER DE ACESSO', 'ID PRANCHA', 'ID COMISSIONAMENTO N1', 'ID COMISSIONAMENTO N2']


CONFIG_GOOGLE = {'GOOGLE_CREDENCIAIS': '{}', 'PLANILHA_OBRAS_ID': 'planilha-teste'}


def linha(**valores) -> list[str]:
    base = {'Nº OBRA': '1234', 'CLIENTE': 'Ana', 'kWp': '9,84', 'CIDADE': 'Brasília', 'UF': 'DF',
            'DISTRIBUIDORA': 'Neoenergia Brasília', 'FECHAMENTO': '01/09/2026', 'VENDEDOR': 'Fulano',
            'FORMA DE PAGAMENTO': 'Financiamento', 'VALOR': 'R$ 45.000,00', 'MÓDULOS': '16 - 615Wp Longi',
            'ETAPA ENGENHARIA': 'Projeto', 'DOCUMENTAÇÃO': '10/09/2026', 'HOMOLOGAÇÃO (ENTRADA)': '12/09/2026',
            'APROVAÇÃO DO PROJETO': '20/10/2026', 'PROTOCOLO DISTRIBUIDORA': '2026-998877', 'NOTA FISCAL': '555',
            'ID ART': 'drive-art', 'ID PARECER DE ACESSO': 'drive-parecer'}
    base.update(valores)
    return [base.get(c, '') for c in CABECALHO]


def planilha(*linhas_):
    return [CABECALHO, *linhas_]


class ConversoesTests(SimpleTestCase):
    def test_datas_numeros_e_modulos(self):
        self.assertEqual(obras.ler_data('05/11/2026'), date(2026, 11, 5))
        self.assertEqual(obras.ler_data('05/11/26'), date(2026, 11, 5))
        self.assertIsNone(obras.ler_data('OK'))
        self.assertEqual(obras.ler_numero('9,84'), 9.84)
        self.assertEqual(obras.ler_numero('1.234,5'), 1234.5)
        self.assertEqual(obras.quantidade_modulos('16 - 615Wp Longi'), 16)
        self.assertIsNone(obras.quantidade_modulos(''))

    def test_feriados_moveis_2026(self):
        f = obras.feriados_nacionais(2026)   # Páscoa de 2026 = 05/04
        for d in (date(2026, 2, 16), date(2026, 2, 17), date(2026, 4, 3), date(2026, 6, 4), date(2026, 11, 20)):
            self.assertIn(d, f)

    def test_dias_uteis_pulam_fim_de_semana_e_feriado(self):
        # sexta 13/11/2026 + 7 dias úteis: pula sáb/dom, 20/11 (Consciência Negra, sexta) e o fim de semana seguinte
        self.assertEqual(obras.somar_dias_uteis(date(2026, 11, 13), 7), date(2026, 11, 25))
        self.assertEqual(obras.somar_dias_uteis(date(2026, 11, 13), 5), date(2026, 11, 23))


@override_settings(**CONFIG_GOOGLE)
class ProjetoDaLinhaTests(TestCase):
    def montar(self, **valores):
        cache.clear()
        with patch('integracoes.google.ler_aba', return_value=planilha(linha(**valores))):
            l = obras.linha_do_cliente('1234')
        return obras.montar_projeto(l, '1234')

    def test_etapas_pela_etapa_engenharia_e_datas_de_conclusao(self):
        p = self.montar()
        self.assertEqual([e['status'] for e in p['etapas']],
                         ['concluida', 'concluida', 'andamento', 'proxima', 'proxima'])
        onb, hom, proj = p['etapas'][:3]
        self.assertEqual((onb['inicio'], onb['fim']), ('2026-09-01', '2026-09-10'))
        self.assertEqual((hom['inicio'], hom['fim']), ('2026-09-12', '2026-10-20'))
        self.assertEqual((proj['inicio'], proj['fim']), ('2026-10-20', None))
        self.assertEqual((p['potencia_kwp'], p['modulos'], p['cidade']), (9.84, 16, 'Brasília'))

    def test_nada_sigiloso_vai_para_o_cliente(self):
        texto = str(self.montar())
        for sigiloso in ('Fulano', 'Financiamento', '45.000', '555', '2026-998877', 'drive-art', 'Ana'):
            self.assertNotIn(sigiloso, texto)

    def test_documentos_disponiveis_pela_coluna_de_id(self):
        docs = {d['tipo']: d['disponivel'] for e in self.montar()['etapas'] for d in e['documentos']}
        self.assertEqual(docs, {'art': True, 'parecer': True, 'prancha': False,
                                'comissionamento_1': False, 'comissionamento_2': False})

    def test_prazo_da_vistoria_por_distribuidora(self):
        p = self.montar(**{'ETAPA ENGENHARIA': 'Comissionamento', 'VISTORIA TÉCNICA': '13/11/2026'})
        self.assertEqual(p['etapas'][4]['prazo_vistoria'], '2026-11-25')   # Neoenergia: 7 dias úteis
        self.assertEqual(p['previsao_conclusao'], '2026-11-25')
        p = self.montar(**{'ETAPA ENGENHARIA': 'Comissionamento', 'VISTORIA TÉCNICA': '13/11/2026',
                           'DISTRIBUIDORA': 'Equatorial Goiás'})
        self.assertEqual(p['etapas'][4]['prazo_vistoria'], '2026-11-23')   # Equatorial: 5 dias úteis

    def test_sem_etapa_engenharia_deduz_pelas_datas(self):
        p = self.montar(**{'ETAPA ENGENHARIA': '', 'PROJETO': '01/11/2026'})
        self.assertEqual(p['etapas'][3]['status'], 'andamento')     # projeto concluído → instalação

    def test_copia_guardada_nao_tem_colunas_sigilosas(self):
        cache.clear()
        with patch('integracoes.google.ler_aba', return_value=planilha(linha())):
            obras.linha_do_cliente('1234')
        guardada = str(cache.get(obras.CHAVE_CACHE))
        for sigiloso in ('Fulano', 'Financiamento', '45.000', '555', '2026-998877', 'Ana'):
            self.assertNotIn(sigiloso, guardada)
        self.assertIn('drive-art', guardada)                       # o que a tela usa continua lá

    def test_le_a_planilha_uma_vez_a_cada_5_minutos(self):
        cache.clear()
        with patch('integracoes.google.ler_aba', return_value=planilha(linha())) as ler:
            obras.linha_do_cliente('1234')
            obras.linha_do_cliente('1234')
        self.assertEqual(ler.call_count, 1)


@override_settings(**CONFIG_GOOGLE)
class ProjetoApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.ana = Usuario.objects.create_user('ana@x.com', 'x', nome='Ana', id_cliente='1234')
        self.bia = Usuario.objects.create_user('bia@x.com', 'x', nome='Bia', id_cliente='5678')
        self.admin = Usuario.objects.create_user('adm@x.com', 'x', nome='Adm', perfil='admin')
        self.ler = patch('integracoes.google.ler_aba',
                         return_value=planilha(linha(), linha(**{'Nº OBRA': '5678', 'ID ART': 'drive-art-bia'})))
        self.ler.start()
        self.addCleanup(self.ler.stop)

    def test_cliente_ve_o_proprio_projeto(self):
        self.client.force_authenticate(self.ana)
        r = self.client.get('/api/projeto/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['projeto']['id_cliente'], '1234')

    def test_cliente_nao_ve_projeto_de_outro_nem_pelo_parametro(self):
        self.client.force_authenticate(self.ana)
        r = self.client.get('/api/projeto/?id_cliente=5678')
        self.assertEqual(r.data['projeto']['id_cliente'], '1234')   # o parâmetro é ignorado para o cliente

    def test_numero_da_obra_com_zeros_ou_formatado_na_planilha(self):
        self.assertEqual(obras.numero_obra('0123'), '123')
        self.assertEqual(obras.numero_obra('1.234'), '1234')
        self.assertEqual(obras.numero_obra(''), '')
        self.ana.id_cliente = '123'
        self.ana.save()
        self.ler.stop()
        with patch('integracoes.google.ler_aba', return_value=planilha(linha(**{'Nº OBRA': '0123'}))):
            cache.clear()
            self.client.force_authenticate(self.ana)
            self.assertIsNotNone(self.client.get('/api/projeto/').data['projeto'])
        self.ler.start()

    @patch('integracoes.google._sessao')
    def test_chave_revogada_vira_indisponivel_e_nao_erro_500(self, sessao):
        from google.auth.exceptions import RefreshError
        self.ler.stop()
        sessao.return_value.get.side_effect = RefreshError('invalid_grant')
        cache.clear()
        self.client.force_authenticate(self.ana)
        with self.assertLogs('monitoramento.views', level='WARNING'):
            r = self.client.get('/api/projeto/')
        self.assertEqual(r.status_code, 503)
        self.ler.start()

    def test_cliente_sem_id_ou_sem_linha(self):
        sem = Usuario.objects.create_user('sem@x.com', 'x', nome='Sem')
        self.client.force_authenticate(sem)
        self.assertIsNone(self.client.get('/api/projeto/').data['projeto'])

    def test_equipe_consulta_pelo_id(self):
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get('/api/projeto/?id_cliente=5678').data['projeto']['id_cliente'], '5678')

    @patch('integracoes.google.baixar_arquivo', return_value=google.Arquivo('ART Ana.pdf', 'application/pdf', b'%PDF'))
    def test_baixa_o_documento_da_propria_linha(self, baixar):
        self.client.force_authenticate(self.ana)
        r = self.client.get('/api/projeto/documentos/art/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), b'%PDF')
        baixar.assert_called_once_with('drive-art')                 # nunca o arquivo da Bia
        self.assertIn('attachment', r['Content-Disposition'])

    def test_documento_ainda_nao_disponivel_ou_inexistente(self):
        self.client.force_authenticate(self.ana)
        self.assertEqual(self.client.get('/api/projeto/documentos/prancha/').status_code, 404)
        self.assertEqual(self.client.get('/api/projeto/documentos/qualquer/').status_code, 404)

    @override_settings(GOOGLE_CREDENCIAIS='', PLANILHA_OBRAS_ID='')
    def test_planilha_nao_configurada(self):
        self.client.force_authenticate(self.ana)
        with self.assertLogs('monitoramento.views', level='WARNING'):
            r = self.client.get('/api/projeto/')
        self.assertEqual(r.status_code, 503)

    def test_sem_login_nao_acessa(self):
        self.assertEqual(self.client.get('/api/projeto/').status_code, 401)


@override_settings(**CONFIG_GOOGLE)
class GoogleTests(TestCase):
    """Acesso pela conta de serviço (sessão simulada; nenhuma chamada real ao Google)."""

    def resposta(self, status=200, dados=None, conteudo=b''):
        from unittest.mock import MagicMock
        r = MagicMock(status_code=status, content=conteudo)
        r.json.return_value = dados or {}
        return r

    @patch('integracoes.google._sessao')
    def test_le_a_aba_da_planilha(self, sessao):
        sessao.return_value.get.return_value = self.resposta(dados={'values': [['Nº OBRA'], ['1234']]})
        self.assertEqual(google.ler_aba('planilha-teste', 'OBRAS'), [['Nº OBRA'], ['1234']])

    @patch('integracoes.google._sessao')
    def test_sem_permissao_vira_google_erro(self, sessao):
        sessao.return_value.get.return_value = self.resposta(status=403, dados={'error': {'message': 'The caller does not have permission'}})
        with self.assertRaisesMessage(google.GoogleErro, '403'):
            google.ler_aba('planilha-teste', 'OBRAS')

    @patch('integracoes.google._sessao')
    def test_documento_do_google_vira_pdf(self, sessao):
        pdf = self.resposta()
        pdf.iter_content.return_value = [b'%PDF-', b'prancha']
        sessao.return_value.get.side_effect = [
            self.resposta(dados={'name': 'Prancha', 'mimeType': 'application/vnd.google-apps.document'}), pdf]
        arquivo = google.baixar_arquivo('drive-prancha')
        self.assertEqual((arquivo.nome, arquivo.tipo, b''.join(arquivo.conteudo)),
                         ('Prancha.pdf', 'application/pdf', b'%PDF-prancha'))   # entregue em partes
        self.assertTrue(sessao.return_value.get.call_args.args[0].endswith('/export'))

    @patch('integracoes.google._sessao')
    def test_arquivo_acima_de_30_mb_nao_e_baixado(self, sessao):
        sessao.return_value.get.return_value = self.resposta(
            dados={'name': 'Enorme.pdf', 'mimeType': 'application/pdf', 'size': str(80 * 1024 * 1024)})
        with self.assertRaises(google.ArquivoGrande):
            google.baixar_arquivo('drive-enorme')
        self.assertEqual(sessao.return_value.get.call_count, 1)   # nem começa a baixar

    @override_settings(GOOGLE_CREDENCIAIS='nao-e-base64-nem-json')
    def test_chave_invalida_vira_google_erro(self):
        with self.assertRaisesMessage(google.GoogleErro, 'GOOGLE_CREDENCIAIS'):
            google.ler_aba('planilha-teste', 'OBRAS')
