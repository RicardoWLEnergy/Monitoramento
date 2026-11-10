from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Usuario, normalizar_cpf, normalizar_whatsapp


class NormalizarWhatsappTests(TestCase):
    def test_numero_brasileiro_formatado(self):
        self.assertEqual(normalizar_whatsapp('(61) 99999-8888'), '+5561999998888')

    def test_numero_ja_internacional(self):
        self.assertEqual(normalizar_whatsapp('+55 61 99999-8888'), '+5561999998888')

    def test_vazio_vira_none(self):
        self.assertIsNone(normalizar_whatsapp(''))
        self.assertIsNone(normalizar_whatsapp(None))

    def test_numero_invalido(self):
        with self.assertRaises(ValidationError):
            normalizar_whatsapp('123')


class UsuarioTests(TestCase):
    def test_cria_usuario_com_email_e_senha_criptografada(self):
        u = Usuario.objects.create_user('Cliente@Exemplo.com', 'senha-forte-123', nome='Cliente')
        self.assertEqual(u.email, 'cliente@exemplo.com')  # sempre minúsculo
        self.assertEqual(u.perfil, Usuario.Perfil.CLIENTE)
        self.assertNotEqual(u.password, 'senha-forte-123')
        self.assertTrue(u.check_password('senha-forte-123'))
        self.assertFalse(u.is_staff)

    def test_superusuario_e_admin(self):
        u = Usuario.objects.create_superuser('admin@wlenergy.com.br', 'senha-forte-123', nome='Admin')
        self.assertEqual(u.perfil, Usuario.Perfil.ADMIN)
        self.assertTrue(u.is_superuser)
        self.assertTrue(u.is_staff)

    def test_whatsapp_normalizado_ao_salvar(self):
        u = Usuario.objects.create_user('a@a.com', 'x', nome='A', whatsapp='(61) 98888-7777')
        self.assertEqual(u.whatsapp, '+5561988887777')

    def test_varios_usuarios_sem_whatsapp(self):
        Usuario.objects.create_user('a@a.com', 'x', nome='A', whatsapp='')
        Usuario.objects.create_user('b@b.com', 'x', nome='B')  # não conflita no campo único
        self.assertEqual(Usuario.objects.filter(whatsapp__isnull=True).count(), 2)


class CpfTests(TestCase):
    def test_cpf_valido_guarda_so_digitos(self):
        self.assertEqual(normalizar_cpf('529.982.247-25'), '52998224725')

    def test_cpf_com_digito_errado(self):
        with self.assertRaises(ValidationError):
            normalizar_cpf('529.982.247-26')

    def test_cpf_repetido_invalido(self):
        with self.assertRaises(ValidationError):
            normalizar_cpf('111.111.111-11')

    def test_vazio_vira_none(self):
        self.assertIsNone(normalizar_cpf(''))

    def test_usuario_com_cpf_e_mapa(self):
        u = Usuario.objects.create_user('c@x.com', 'x', nome='C', cpf='529.982.247-25',
                                        endereco='SQS 308 Bloco A, Brasília - DF')
        self.assertEqual(u.cpf, '52998224725')
        self.assertEqual(u.cpf_formatado, '529.982.247-25')
        self.assertIn('google.com/maps', u.link_maps)


class AdminUsuariosTests(TestCase):
    """As telas de usuário do /admin precisam abrir com o nosso modelo personalizado."""

    def setUp(self):
        self.admin = Usuario.objects.create_superuser('admin@x.com', 'senha-forte-123', nome='Admin')
        self.client.force_login(self.admin)

    def test_tela_adicionar_abre(self):
        self.assertEqual(self.client.get('/admin/usuarios/usuario/add/').status_code, 200)

    def test_tela_editar_abre(self):
        self.assertEqual(self.client.get(f'/admin/usuarios/usuario/{self.admin.pk}/change/').status_code, 200)

    def test_cria_cliente_pelo_admin(self):
        resposta = self.client.post('/admin/usuarios/usuario/add/', {
            'email': 'Novo@Cliente.com', 'nome': 'Novo Cliente', 'cpf': '529.982.247-25',
            'perfil': 'cliente', 'password1': 'Senha-Forte-987', 'password2': 'Senha-Forte-987',
            'usable_password': 'true',
        })
        self.assertEqual(resposta.status_code, 302, resposta.content[:2000])
        novo = Usuario.objects.get(email='novo@cliente.com')
        self.assertEqual(novo.cpf, '52998224725')
        self.assertTrue(novo.check_password('Senha-Forte-987'))
