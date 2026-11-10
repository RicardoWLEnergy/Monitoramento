from datetime import date, timedelta

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.utils import timezone

from usinas.models import Fabricante, Inversor, Plataforma, Usina

from .models import Alerta, GeracaoDiaria, Leitura
from .particoes import criar_particoes, nome_particao, particoes_existentes, remover_particoes_antigas


class BaseTests(TestCase):
    def setUp(self):
        self.usina = Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.FOXESS,
                                          id_externo='FX-1', nome='Usina Teste')


class LeituraTests(BaseTests):
    def test_mesmo_horario_nao_duplica(self):
        agora = timezone.now()
        Leitura.objects.create(usina=self.usina, data_hora=agora, potencia_kw=5)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Leitura.objects.create(usina=self.usina, data_hora=agora, potencia_kw=6)

    def test_chave_composta_identifica_a_leitura(self):
        agora = timezone.now()
        Leitura.objects.create(usina=self.usina, data_hora=agora, potencia_kw=5)
        leitura = Leitura.objects.get(pk=(self.usina.pk, agora))
        self.assertEqual(leitura.potencia_kw, 5)

    def test_leitura_vai_para_a_particao_do_mes(self):
        agora = timezone.now()
        Leitura.objects.create(usina=self.usina, data_hora=agora, potencia_kw=5)
        local = timezone.localtime(agora)
        with connection.cursor() as c:
            c.execute(f'SELECT count(*) FROM "{nome_particao(local.date())}"')
            self.assertEqual(c.fetchone()[0], 1)

    def test_mes_sem_particao_e_recusado(self):
        muito_antigo = timezone.now() - timedelta(days=365 * 3)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Leitura.objects.create(usina=self.usina, data_hora=muito_antigo, potencia_kw=5)


class ParticoesTests(TestCase):
    def test_migracao_cria_13_meses_para_tras_e_3_a_frente(self):
        hoje = date.today()
        existentes = particoes_existentes()
        self.assertIn(nome_particao(hoje), existentes)
        self.assertGreaterEqual(len(existentes), 16)

    def test_criar_e_idempotente(self):
        antes = particoes_existentes()
        criar_particoes(meses_depois=3)
        self.assertEqual(particoes_existentes(), antes)

    def test_remove_somente_alem_da_retencao(self):
        hoje = date.today()
        criar_particoes(meses_antes=20, meses_depois=0, hoje=hoje)   # simula histórico longo
        removidas = remover_particoes_antigas(retencao_meses=13, hoje=hoje)

        restantes = particoes_existentes()
        ate_hoje = [p for p in restantes if p <= nome_particao(hoje)]
        self.assertTrue(removidas)
        self.assertIn(nome_particao(hoje), restantes)
        self.assertEqual(len(ate_hoje), 13)   # mês atual + 12 anteriores


class GeracaoDiariaTests(BaseTests):
    def test_um_registro_por_dia(self):
        GeracaoDiaria.objects.create(usina=self.usina, data=date(2026, 11, 9), energia_kwh=40)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GeracaoDiaria.objects.create(usina=self.usina, data=date(2026, 11, 9), energia_kwh=41)


class AlertaTests(BaseTests):
    def test_nao_abre_o_mesmo_alerta_duas_vezes(self):
        Alerta.objects.create(usina=self.usina, tipo=Alerta.Tipo.OFFLINE)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Alerta.objects.create(usina=self.usina, tipo=Alerta.Tipo.OFFLINE)

    def test_reabre_depois_de_encerrado(self):
        alerta = Alerta.objects.create(usina=self.usina, tipo=Alerta.Tipo.OFFLINE)
        alerta.fim = timezone.now()
        alerta.save()
        novo = Alerta.objects.create(usina=self.usina, tipo=Alerta.Tipo.OFFLINE)
        self.assertTrue(novo.aberto)
        self.assertFalse(alerta.aberto)

    def test_alertas_de_inversores_diferentes_podem_coexistir(self):
        inv1 = Inversor.objects.create(usina=self.usina, numero_serie='SN1')
        inv2 = Inversor.objects.create(usina=self.usina, numero_serie='SN2')
        Alerta.objects.create(usina=self.usina, inversor=inv1, tipo=Alerta.Tipo.FALHA_INVERSOR)
        Alerta.objects.create(usina=self.usina, inversor=inv2, tipo=Alerta.Tipo.FALHA_INVERSOR)
        self.assertEqual(self.usina.alertas.count(), 2)

    def test_fim_antes_do_inicio_recusado(self):
        agora = timezone.now()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Alerta.objects.create(usina=self.usina, tipo=Alerta.Tipo.OFFLINE,
                                  inicio=agora, fim=agora - timedelta(minutes=1))
