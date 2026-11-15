"""Testes do login com código pelo WhatsApp (a uazapi é sempre simulada: nenhum envio real)."""
import re
from datetime import timedelta
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase

from integracoes.uazapi import UazapiErro

from .models import CodigoAcesso, Usuario, mascarar_whatsapp

PEDIR, ENTRAR = '/api/auth/codigo/', '/api/auth/codigo/entrar/'


@override_settings(UAZAPI_URL='https://teste.uazapi.com', UAZAPI_TOKEN='token-de-teste')
@patch('usuarios.views.enviar_texto')
class LoginComCodigoTests(APITestCase):
    def setUp(self):
        self.ana = Usuario.objects.create_user('ana@x.com', 'Senha-Forte-123', nome='Ana', whatsapp='(61) 99999-0142')

    def pedir(self, email='ana@x.com'):
        return self.client.post(PEDIR, {'email': email}, format='json')

    def codigo_enviado(self, enviar) -> str:
        return re.search(r'\d{6}', enviar.call_args.args[1]).group()

    def test_envia_para_o_whatsapp_do_email_e_mostra_o_final_do_numero(self, enviar):
        r = self.pedir('Ana@X.com ')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['detail'], 'Código enviado para o número (61) * ****-0142.')
        numero, texto = enviar.call_args.args
        self.assertEqual(numero, '+5561999990142')
        self.assertIn('Código de acesso:', texto)
        self.assertIn(f'*{self.codigo_enviado(enviar)}*', texto)   # código em negrito, em linha própria
        self.assertNotIn(self.codigo_enviado(enviar), CodigoAcesso.objects.get().codigo_hash)   # banco só tem o hash

    def test_entra_com_o_codigo_certo_uma_unica_vez(self, enviar):
        self.pedir()
        codigo = self.codigo_enviado(enviar)
        r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': codigo}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)
        self.assertIn('refresh', r.data)
        self.ana.refresh_from_db()
        self.assertIsNotNone(self.ana.last_login)
        r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': codigo}, format='json')
        self.assertEqual(r.status_code, 400)                              # já usado

    def test_codigo_expira_em_5_minutos(self, enviar):
        self.pedir()
        CodigoAcesso.objects.update(expira_em=timezone.now() - timedelta(seconds=1))
        r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': self.codigo_enviado(enviar)}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('expirado', r.data['detail'])

    def test_5_tentativas_erradas_bloqueiam_o_codigo(self, enviar):
        self.pedir()
        certo = self.codigo_enviado(enviar)
        errado = f'{(int(certo) + 1) % 1_000_000:06d}'
        for restantes in (4, 3, 2, 1):
            r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': errado}, format='json')
            self.assertIn(f'{restantes} tentativa', r.data['detail'])
        r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': errado}, format='json')
        self.assertIn('bloqueado', r.data['detail'])
        r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': certo}, format='json')
        self.assertEqual(r.status_code, 400)                              # nem o certo vale mais

    def test_pedir_outro_invalida_o_anterior(self, enviar):
        self.pedir()
        primeiro = self.codigo_enviado(enviar)
        CodigoAcesso.objects.update(criado_em=timezone.now() - timedelta(minutes=2))   # passou o intervalo
        self.pedir()
        segundo = self.codigo_enviado(enviar)
        if primeiro != segundo:
            r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': primeiro}, format='json')
            self.assertEqual(r.status_code, 400)
        r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': segundo}, format='json')
        self.assertEqual(r.status_code, 200)

    def test_1_envio_por_minuto_e_5_por_hora(self, enviar):
        self.pedir()
        r = self.pedir()
        self.assertEqual(r.status_code, 429)
        self.assertIn('Aguarde', r.data['detail'])
        for minutos in (10, 20, 30, 40):
            CodigoAcesso.objects.create(usuario=self.ana, codigo_hash='x', criado_em=timezone.now() - timedelta(minutes=minutos),
                                        expira_em=timezone.now())
        CodigoAcesso.objects.update(criado_em=timezone.now() - timedelta(minutes=5))
        r = self.pedir()
        self.assertEqual(r.status_code, 429)
        self.assertIn('última hora', r.data['detail'])
        self.assertEqual(enviar.call_count, 1)

    def test_teto_de_10_codigos_por_dia(self, enviar):
        agora = timezone.now()
        for horas in range(2, 12):                    # 10 códigos nas últimas 24 h, fora da última hora
            CodigoAcesso.objects.create(usuario=self.ana, codigo_hash='x', criado_em=agora - timedelta(hours=horas),
                                        expira_em=agora)
        with self.assertLogs('usuarios.views', level='WARNING'):
            r = self.pedir()
        self.assertEqual(r.status_code, 429)
        self.assertIn('hoje', r.data['detail'])
        enviar.assert_not_called()

    def test_sem_whatsapp_desativado_ou_inexistente_nao_envia(self, enviar):
        Usuario.objects.create_user('sem@x.com', 'Senha-Forte-123', nome='Sem WhatsApp')
        Usuario.objects.create_user('inativo@x.com', 'Senha-Forte-123', nome='Inativo', whatsapp='61988887777',
                                    is_active=False)
        for email in ('sem@x.com', 'inativo@x.com', 'ninguem@x.com'):
            r = self.pedir(email)
            self.assertEqual(r.status_code, 400)
            self.assertIn('Não foi possível enviar', r.data['detail'])
        enviar.assert_not_called()

    def test_falha_na_uazapi_nao_conta_e_mostra_mensagem_amigavel(self, enviar):
        enviar.side_effect = UazapiErro('uazapi HTTP 500: WhatsApp client is not connected')
        with self.assertLogs('usuarios.views', level='WARNING') as registro:
            r = self.pedir()
        self.assertEqual(r.status_code, 503)
        self.assertIn('Tente de novo em alguns minutos', r.data['detail'])
        self.assertNotIn('token-de-teste', ' '.join(registro.output))   # token nunca no registro
        self.assertEqual(CodigoAcesso.objects.count(), 0)                # pode tentar de novo na hora

    @override_settings(UAZAPI_URL='', UAZAPI_TOKEN='')
    def test_sem_uazapi_configurada(self, enviar):
        with self.assertLogs('usuarios.views', level='WARNING'):
            self.assertEqual(self.pedir().status_code, 503)
        enviar.assert_not_called()

    def test_codigo_mal_formado(self, enviar):
        r = self.client.post(ENTRAR, {'email': 'ana@x.com', 'codigo': '12ab'}, format='json')
        self.assertEqual(r.status_code, 400)


class MascaraWhatsappTests(APITestCase):
    def test_formatos(self):
        self.assertEqual(mascarar_whatsapp('+5561999990142'), '(61) * ****-0142')   # celular
        self.assertEqual(mascarar_whatsapp('+556133330142'), '(61) ****-0142')      # fixo
        self.assertEqual(mascarar_whatsapp('+14155550142'), '****-0142')            # outro país


@override_settings(UAZAPI_URL='https://teste.uazapi.com/', UAZAPI_TOKEN='token-de-teste')
class ClienteUazapiTests(APITestCase):
    @patch('integracoes.uazapi.requests.post')
    def test_envia_texto_no_formato_da_documentacao(self, post):
        from integracoes.uazapi import enviar_texto
        post.return_value.status_code = 200
        post.return_value.json.return_value = {'response': {'status': 'success'}}
        enviar_texto('+5561999990142', 'olá')
        args, kwargs = post.call_args
        self.assertEqual(args[0], 'https://teste.uazapi.com/send/text')
        self.assertEqual(kwargs['json'], {'number': '5561999990142', 'text': 'olá'})
        self.assertEqual(kwargs['headers']['token'], 'token-de-teste')

    @patch('integracoes.uazapi.requests.post')
    def test_erro_da_uazapi_vira_uazapi_erro_sem_o_token(self, post):
        from integracoes.uazapi import enviar_texto
        post.return_value.status_code = 401
        post.return_value.json.return_value = {'error': 'Invalid token'}
        with self.assertRaises(UazapiErro) as erro:
            enviar_texto('+5561999990142', 'olá')
        self.assertIn('401', str(erro.exception))
        self.assertNotIn('token-de-teste', str(erro.exception))
