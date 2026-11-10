"""Testes da coleta automática (APIs simuladas, sem rede)."""
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from usinas.models import Fabricante, Plataforma, Usina

from .coleta import Relatorio
from .coletor import Clientes, Trava, ciclo_tempo_real, rotina_diaria


def relatorio(inversores=0, leituras=0, dias=0, falhas=None):
    return Relatorio(inversores=inversores, leituras=leituras, dias=dias, falhas=falhas or [])


class ColetorBase(TestCase):
    def setUp(self):
        self.fox = Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.WEG, id_externo='fx', nome='Fox')
        self.hua = Usina.objects.create(plataforma=Plataforma.HUAWEI, fabricante=Fabricante.HUAWEI, id_externo='NE=1', nome='Hua')
        self.clientes = Clientes(_foxess=MagicMock(name='api_fox'), _huawei=MagicMock(name='api_hua'))


@patch('integracoes.coletor.coleta_huawei')
@patch('integracoes.coletor.coleta')
class CicloTempoRealTests(ColetorBase):
    def test_chama_as_duas_plataformas_com_os_mesmos_clientes(self, coleta, huawei):
        coleta.atualizar_tempo_real.return_value = relatorio(inversores=2, leituras=1)
        huawei.atualizar_tempo_real.return_value = relatorio(inversores=1, leituras=1)
        r = ciclo_tempo_real(self.clientes)
        self.assertEqual((r.inversores, r.leituras), (3, 2))
        coleta.atualizar_tempo_real.assert_called_once_with(api=self.clientes._foxess)
        huawei.atualizar_tempo_real.assert_called_once_with(api=self.clientes._huawei)

    def test_erro_em_uma_plataforma_nao_para_a_outra(self, coleta, huawei):
        coleta.atualizar_tempo_real.side_effect = RuntimeError('FoxESS fora do ar')
        huawei.atualizar_tempo_real.return_value = relatorio(inversores=1)
        with self.assertLogs('coletor', level='ERROR'):
            r = ciclo_tempo_real(self.clientes)
        self.assertEqual(r.inversores, 1)
        self.assertIn('FoxESS fora do ar', r.erros[0])

    def test_plataforma_sem_usinas_ativas_nem_e_chamada(self, coleta, huawei):
        self.hua.desativar()
        coleta.atualizar_tempo_real.return_value = relatorio()
        ciclo_tempo_real(self.clientes)
        huawei.atualizar_tempo_real.assert_not_called()


@patch('integracoes.coletor.remover_particoes_antigas', return_value=[])
@patch('integracoes.coletor.criar_particoes')
@patch('integracoes.coletor.coleta_huawei')
@patch('integracoes.coletor.coleta')
class RotinaDiariaTests(ColetorBase):
    def test_energia_dos_ultimos_dias_curva_de_ontem_e_particoes(self, coleta, huawei, criar, remover):
        for modulo in (coleta, huawei):
            modulo.importar_geracao_diaria.return_value = relatorio(dias=3)
            modulo.importar_curvas.return_value = relatorio(leituras=288)
        hoje = timezone.localdate()

        r = rotina_diaria(self.clientes)

        self.assertEqual((r.dias, r.leituras), (6, 576))
        criar.assert_called_once()
        remover.assert_called_once()
        args = coleta.importar_geracao_diaria.call_args.args
        self.assertEqual((args[1], args[2]), (hoje - timedelta(days=2), hoje))
        args = coleta.importar_curvas.call_args.args
        self.assertEqual((args[1], args[2]), (hoje - timedelta(days=1), hoje - timedelta(days=1)))

    def test_curva_huawei_bloqueada_nao_insiste(self, coleta, huawei, criar, remover):
        coleta.importar_geracao_diaria.return_value = coleta.importar_curvas.return_value = relatorio()
        huawei.importar_geracao_diaria.return_value = relatorio(dias=3)
        huawei.importar_curvas.return_value = relatorio(falhas=['Curva de 5 min não liberada na conta Northbound'])

        with self.assertLogs('coletor', level='WARNING'):
            rotina_diaria(self.clientes)
        self.assertTrue(self.clientes.curva_huawei_bloqueada)
        rotina_diaria(self.clientes)                                   # dia seguinte
        self.assertEqual(huawei.importar_curvas.call_count, 1)         # não tentou de novo
        self.assertEqual(huawei.importar_geracao_diaria.call_count, 2)  # energia diária continua

    def test_erro_numa_usina_nao_para_as_outras(self, coleta, huawei, criar, remover):
        coleta.importar_geracao_diaria.side_effect = RuntimeError('timeout')
        huawei.importar_geracao_diaria.return_value = relatorio(dias=3)
        huawei.importar_curvas.return_value = relatorio()
        with self.assertLogs('coletor', level='ERROR'):
            r = rotina_diaria(self.clientes)
        self.assertEqual(r.dias, 3)
        self.assertTrue(any('timeout' in e for e in r.erros))


class TravaTests(TestCase):
    def test_segundo_coletor_nao_obtem_e_trava_sobrevive_ao_fechar_conexoes(self):
        from django.db import close_old_connections, connection
        primeira, segunda = Trava(), Trava()
        self.assertTrue(primeira.obter())
        connection.close()                     # o ciclo do coletor fecha as conexões normais...
        close_old_connections()
        self.assertFalse(segunda.obter())      # ...e a trava continua valendo
        primeira.liberar()
        terceira = Trava()
        self.assertTrue(terceira.obter())      # liberada, outro coletor pode iniciar
        terceira.liberar()


class ComandoColetarTests(TestCase):
    @patch('integracoes.management.commands.coletar.rotina_diaria')
    @patch('integracoes.management.commands.coletar.ciclo_tempo_real')
    def test_uma_vez_faz_tempo_real_e_rotina_diaria(self, ciclo, rotina):
        from .coletor import Resumo
        ciclo.return_value = rotina.return_value = Resumo()
        with self.assertLogs('coletor', level='INFO'):
            call_command('coletar', '--uma-vez', stdout=StringIO())
        ciclo.assert_called_once()
        rotina.assert_called_once()

    @patch('integracoes.management.commands.coletar.Trava')
    def test_segundo_coletor_nao_inicia(self, Trava):
        Trava.return_value.obter.return_value = False
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, 'Já existe um coletor rodando'):
            call_command('coletar', '--uma-vez', stdout=StringIO())
