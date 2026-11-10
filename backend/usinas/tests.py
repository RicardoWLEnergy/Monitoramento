from django.db import IntegrityError, transaction
from django.test import TestCase

from usuarios.models import Usuario

from .models import Fabricante, GeracaoEsperada, Inversor, Plataforma, Usina


def criar_usina(**campos):
    dados = {'plataforma': Plataforma.FOXESS, 'fabricante': Fabricante.WEG, 'id_externo': 'NE-1',
             'nome': 'Usina Teste', 'potencia_kwp': 10}
    dados.update(campos)
    return Usina.objects.create(**dados)


class UsinaTests(TestCase):
    def test_mesma_usina_da_mesma_plataforma_nao_duplica(self):
        criar_usina()
        with self.assertRaises(IntegrityError), transaction.atomic():
            criar_usina(nome='Outra')

    def test_mesmo_id_em_plataformas_diferentes_e_permitido(self):
        criar_usina(plataforma=Plataforma.FOXESS)
        criar_usina(plataforma=Plataforma.HUAWEI)
        self.assertEqual(Usina.objects.count(), 2)

    def test_vinculo_usuario_usina_muitos_para_muitos(self):
        usina_a, usina_b = criar_usina(id_externo='A'), criar_usina(id_externo='B')
        cliente_1 = Usuario.objects.create_user('c1@x.com', 'x', nome='C1')
        cliente_2 = Usuario.objects.create_user('c2@x.com', 'x', nome='C2')

        usina_a.usuarios.add(cliente_1, cliente_2)   # uma usina, dois clientes
        cliente_1.usinas.add(usina_b)                # um cliente, duas usinas

        self.assertEqual(usina_a.usuarios.count(), 2)
        self.assertEqual(set(cliente_1.usinas.all()), {usina_a, usina_b})
        self.assertEqual(list(cliente_2.usinas.all()), [usina_a])

    def test_apagar_usina_apaga_inversores(self):
        usina = criar_usina()
        Inversor.objects.create(usina=usina, numero_serie='SN1')
        usina.delete()
        self.assertFalse(Inversor.objects.exists())


class GeracaoEsperadaTests(TestCase):
    def test_um_valor_por_mes(self):
        usina = criar_usina()
        GeracaoEsperada.objects.create(usina=usina, mes=1, energia_kwh=1000)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GeracaoEsperada.objects.create(usina=usina, mes=1, energia_kwh=900)

    def test_mes_invalido_recusado_pelo_banco(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            GeracaoEsperada.objects.create(usina=criar_usina(), mes=13, energia_kwh=1000)


    def test_link_maps_pelo_endereco_ou_coordenadas(self):
        usina = criar_usina(endereco='CA V Pires Ch 29', cidade='Brasilia')
        self.assertIn('query=CA+V+Pires+Ch+29%2C+Brasilia', usina.link_maps)
        usina.latitude, usina.longitude = -15.8, -47.9
        self.assertTrue(usina.link_maps.endswith('query=-15.8,-47.9'))
