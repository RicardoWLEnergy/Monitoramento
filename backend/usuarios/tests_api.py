"""Testes da API de login e usuários, por perfil."""
from types import SimpleNamespace
from unittest.mock import patch

from rest_framework.test import APITestCase

from integracoes.cadastro import CadastroErro

from .models import Usuario


class ApiBase(APITestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_user('admin@x.com', 'Senha-Forte-123', nome='Admin', perfil='admin')
        self.colab = Usuario.objects.create_user('colab@x.com', 'Senha-Forte-123', nome='Colab', perfil='colaborador')
        self.cliente = Usuario.objects.create_user('cli@x.com', 'Senha-Forte-123', nome='Cliente', perfil='cliente')

    def entrar(self, usuario):
        self.client.force_authenticate(usuario)


class AuthApiTests(ApiBase):
    def test_login_aceita_email_com_maiusculas_e_devolve_tokens(self):
        r = self.client.post('/api/auth/login/', {'email': 'Admin@X.com', 'password': 'Senha-Forte-123'})
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)
        self.assertIn('refresh', r.data)

    def test_login_com_senha_errada(self):
        r = self.client.post('/api/auth/login/', {'email': 'admin@x.com', 'password': 'errada'})
        self.assertEqual(r.status_code, 401)

    def test_usuario_desativado_nao_entra(self):
        self.cliente.is_active = False
        self.cliente.save()
        r = self.client.post('/api/auth/login/', {'email': 'cli@x.com', 'password': 'Senha-Forte-123'})
        self.assertEqual(r.status_code, 401)

    def test_renovar_token(self):
        refresh = self.client.post('/api/auth/login/', {'email': 'cli@x.com', 'password': 'Senha-Forte-123'}).data['refresh']
        r = self.client.post('/api/auth/renovar/', {'refresh': refresh})
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)

    def test_api_exige_login(self):
        self.assertEqual(self.client.get('/api/usinas/').status_code, 401)

    def test_eu_mostra_perfil_e_altera_so_nome_e_whatsapp(self):
        self.entrar(self.cliente)
        self.assertEqual(self.client.get('/api/auth/eu/').data['perfil'], 'cliente')
        r = self.client.patch('/api/auth/eu/', {'nome': 'Novo Nome', 'whatsapp': '(61) 98888-7777', 'perfil': 'admin'})
        self.assertEqual(r.status_code, 200)
        self.cliente.refresh_from_db()
        self.assertEqual((self.cliente.nome, self.cliente.whatsapp, self.cliente.perfil),
                         ('Novo Nome', '+5561988887777', 'cliente'))

    def test_trocar_senha(self):
        self.entrar(self.cliente)
        r = self.client.post('/api/auth/trocar-senha/', {'senha_atual': 'errada', 'senha_nova': 'Outra-Senha-456'})
        self.assertEqual(r.status_code, 400)
        r = self.client.post('/api/auth/trocar-senha/', {'senha_atual': 'Senha-Forte-123', 'senha_nova': 'Outra-Senha-456'})
        self.assertEqual(r.status_code, 200)
        self.cliente.refresh_from_db()
        self.assertTrue(self.cliente.check_password('Outra-Senha-456'))


class UsuariosApiTests(ApiBase):
    def test_cliente_nao_acessa(self):
        self.entrar(self.cliente)
        self.assertEqual(self.client.get('/api/usuarios/').status_code, 403)

    def test_colaborador_so_ve_clientes(self):
        self.entrar(self.colab)
        emails = [u['email'] for u in self.client.get('/api/usuarios/').data['results']]
        self.assertEqual(emails, ['cli@x.com'])

    def test_colaborador_cria_sempre_cliente(self):
        self.entrar(self.colab)
        r = self.client.post('/api/usuarios/', {'email': 'novo@x.com', 'nome': 'Novo', 'perfil': 'admin',
                                                'cpf': '529.982.247-25', 'senha': 'Senha-Forte-789'})
        self.assertEqual(r.status_code, 201, r.data)
        novo = Usuario.objects.get(email='novo@x.com')
        self.assertEqual((novo.perfil, novo.cpf), ('cliente', '52998224725'))
        self.assertTrue(novo.check_password('Senha-Forte-789'))

    def test_admin_cria_colaborador_sem_senha(self):
        self.entrar(self.admin)
        r = self.client.post('/api/usuarios/', {'email': 'c2@x.com', 'nome': 'C2', 'perfil': 'colaborador'})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(Usuario.objects.get(email='c2@x.com').has_usable_password())

    def test_cpf_e_email_duplicados(self):
        self.entrar(self.admin)
        self.client.post('/api/usuarios/', {'email': 'a1@x.com', 'nome': 'A1', 'cpf': '52998224725'})
        r = self.client.post('/api/usuarios/', {'email': 'A1@X.com', 'nome': 'A2', 'cpf': '529.982.247-25'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('email', r.data)
        self.assertIn('cpf', r.data)

    def test_cpf_invalido(self):
        self.entrar(self.admin)
        r = self.client.post('/api/usuarios/', {'email': 'a@x.com', 'nome': 'A', 'cpf': '123.456.789-00'})
        self.assertEqual(r.status_code, 400)

    def test_sem_exclusao_apenas_desativacao(self):
        self.entrar(self.admin)
        self.assertEqual(self.client.delete(f'/api/usuarios/{self.cliente.pk}/').status_code, 405)
        r = self.client.patch(f'/api/usuarios/{self.cliente.pk}/', {'ativo': False})
        self.assertEqual(r.status_code, 200)
        self.cliente.refresh_from_db()
        self.assertFalse(self.cliente.is_active)

    def test_colaborador_nao_muda_perfil(self):
        self.entrar(self.colab)
        self.client.patch(f'/api/usuarios/{self.cliente.pk}/', {'perfil': 'admin'})
        self.cliente.refresh_from_db()
        self.assertEqual(self.cliente.perfil, 'cliente')

    @patch('usuarios.views.cadastrar_por_sn')
    def test_vincular_inversor(self, cadastrar):
        cadastrar.return_value = SimpleNamespace(
            usina=SimpleNamespace(id=7, nome='UFV Teste'), usina_nova=True, inversores=['SN1'], reativada=False)
        self.entrar(self.colab)
        r = self.client.post(f'/api/usuarios/{self.cliente.pk}/vincular-inversor/', {'plataforma': 'foxess', 'sn': 'SN1'})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['usina'], {'id': 7, 'nome': 'UFV Teste'})
        cadastrar.assert_called_once_with('foxess', 'SN1', self.cliente)

    @patch('usuarios.views.cadastrar_por_sn')
    def test_vincular_inversor_erro_vira_mensagem(self, cadastrar):
        cadastrar.side_effect = CadastroErro('Inversor SN9 não encontrado na conta FoxESS.')
        self.entrar(self.admin)
        r = self.client.post(f'/api/usuarios/{self.cliente.pk}/vincular-inversor/', {'plataforma': 'foxess', 'sn': 'SN9'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('não encontrado', r.data['detail'])
