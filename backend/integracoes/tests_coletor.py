"""Testes da coleta automática (APIs simuladas, sem rede)."""
from datetime import date, timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from monitoramento.models import ImportacaoHistorico
from usinas.models import Fabricante, Plataforma, Usina

from .coleta import Relatorio
from .coletor import Clientes, Trava, ciclo_tempo_real, executar_passo, processar_fila, rotina_diaria


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


def relogio_parado():
    """Relógio que nunca chega ao prazo: processar_fila só para quando a fila esvazia."""
    return 0.0


@patch('integracoes.coletor.coleta.limite_curvas', return_value=date(2025, 11, 1))
@patch('integracoes.coletor.timezone.localdate', return_value=date(2026, 11, 15))
@patch('integracoes.coletor.coleta_huawei')
@patch('integracoes.coletor.coleta.importar_curvas')
@patch('integracoes.coletor.coleta.importar_geracao_diaria')
class FilaImportacaoTests(ColetorBase):
    """Importações pedidas na tela, feitas pelo coletor em pedaços."""

    def pedir(self, usina=None, inicio=date(2026, 10, 30), fim=date(2026, 11, 2), curvas=True):
        return ImportacaoHistorico.objects.create(usina=usina or self.fox, inicio=inicio, fim=fim, curvas=curvas)

    def test_importa_energia_por_mes_e_curva_por_dia_ate_concluir(self, diaria, curvas, huawei, hoje, limite):
        diaria.return_value = relatorio(dias=2)
        curvas.return_value = relatorio(dias=1, leituras=200)
        imp = self.pedir()

        self.assertEqual(processar_fila(self.clientes, prazo=1, relogio=relogio_parado), 6)   # 2 meses + 4 dias

        imp.refresh_from_db()
        self.assertEqual(imp.status, ImportacaoHistorico.Status.CONCLUIDA)
        self.assertEqual((imp.passos_feitos, imp.passos_total), (6, 6))
        self.assertEqual((imp.dias_energia, imp.dias_curva, imp.leituras), (4, 4, 800))
        meses = [c.args[1:3] for c in diaria.call_args_list]
        self.assertEqual(meses, [(date(2026, 11, 1), date(2026, 11, 2)), (date(2026, 10, 30), date(2026, 10, 31))])
        dias = [c.args[1] for c in curvas.call_args_list]
        self.assertEqual(dias, [date(2026, 11, 2), date(2026, 11, 1), date(2026, 10, 31), date(2026, 10, 30)])
        self.assertTrue(all(c.kwargs['api'] is self.clientes._foxess for c in diaria.call_args_list))

    def test_para_no_prazo_do_tempo_real_e_continua_depois(self, diaria, curvas, huawei, hoje, limite):
        diaria.return_value = relatorio(dias=2)
        curvas.return_value = relatorio(dias=1)
        imp = self.pedir()
        tempos = iter([0, 0, 0, 999])   # 3 pedaços e chega a hora do tempo real

        self.assertEqual(processar_fila(self.clientes, prazo=100, relogio=lambda: next(tempos)), 3)
        imp.refresh_from_db()
        self.assertEqual((imp.status, imp.etapa, imp.passos_feitos), ('importando', 'curva', 3))
        self.assertEqual(imp.cursor, date(2026, 11, 1))          # progresso salvo: próximo dia a importar

        # Coletor reiniciado (clientes novos): continua de onde parou, sem refazer o que já foi
        processar_fila(Clientes(_foxess=MagicMock(), _huawei=MagicMock()), prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual(imp.status, 'concluida')
        self.assertEqual(diaria.call_count, 2)
        self.assertEqual(curvas.call_count, 4)

    def test_sem_curva_so_energia(self, diaria, curvas, huawei, hoje, limite):
        diaria.return_value = relatorio(dias=4)
        imp = self.pedir(curvas=False)
        processar_fila(self.clientes, prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual((imp.status, imp.passos_total), ('concluida', 2))
        curvas.assert_not_called()

    def test_fila_por_ordem_de_chegada(self, diaria, curvas, huawei, hoje, limite):
        diaria.return_value = huawei.importar_geracao_diaria.return_value = relatorio(dias=1)
        primeira = self.pedir(curvas=False, inicio=date(2026, 11, 1))
        segunda = self.pedir(usina=self.hua, curvas=False, inicio=date(2026, 11, 1))
        tempos = iter([0, 999])
        processar_fila(self.clientes, prazo=100, relogio=lambda: next(tempos))
        primeira.refresh_from_db()
        segunda.refresh_from_db()
        self.assertEqual((primeira.status, segunda.status), ('concluida', 'fila'))

    def test_huawei_curva_em_janelas_de_3_dias_e_para_se_nao_liberada(self, diaria, curvas, huawei, hoje, limite):
        huawei.importar_geracao_diaria.return_value = relatorio(dias=10)
        huawei.importar_curvas.return_value = relatorio(falhas=['Curva de 5 min não liberada na conta Northbound'])
        imp = self.pedir(usina=self.hua, inicio=date(2026, 11, 1), fim=date(2026, 11, 10))
        processar_fila(self.clientes, prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual(imp.passos_total, 1 + 4)                         # 1 mês + 10 dias em janelas de 3
        self.assertEqual(huawei.importar_curvas.call_count, 1)            # não insiste nos outros dias
        self.assertEqual(huawei.importar_curvas.call_args.args[1:3], (date(2026, 11, 8), date(2026, 11, 10)))
        self.assertEqual(imp.status, 'concluida')
        self.assertTrue(self.clientes.curva_huawei_bloqueada)
        self.assertIn('não liberada', imp.falhas[0])

    def test_falhas_da_plataforma_ficam_registradas_sem_parar(self, diaria, curvas, huawei, hoje, limite):
        diaria.return_value = relatorio(falhas=['SN1 11/2026: errno 40257'])
        imp = self.pedir(curvas=False)
        processar_fila(self.clientes, prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual(imp.status, 'concluida')
        self.assertEqual(imp.falhas, ['SN1 11/2026: errno 40257'])

    def test_erro_inesperado_encerra_so_a_importacao(self, diaria, curvas, huawei, hoje, limite):
        diaria.side_effect = RuntimeError('banco caiu')
        imp = self.pedir()
        with self.assertLogs('coletor', level='ERROR'):
            processar_fila(self.clientes, prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual(imp.status, 'erro')
        self.assertIn('banco caiu', imp.falhas[0])

    def test_queda_de_rede_pausa_e_retoma_sem_perder_o_ponto(self, diaria, curvas, huawei, hoje, limite):
        import requests
        diaria.side_effect = [requests.ConnectionError('sem rede'), relatorio(dias=2), relatorio(dias=2)]
        curvas.return_value = relatorio(dias=1)
        imp = self.pedir()
        with self.assertLogs('coletor', level='WARNING'):
            processar_fila(self.clientes, prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual((imp.status, imp.passos_feitos, imp.erros_temporarios), ('importando', 0, 1))
        self.assertIsNotNone(imp.tentar_apos)                   # pausada: não roda de novo agora
        self.assertEqual(diaria.call_count, 1)

        ImportacaoHistorico.objects.update(tentar_apos=None)   # passaram os 10 min
        processar_fila(self.clientes, prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual((imp.status, imp.erros_temporarios), ('concluida', 0))

    def test_desiste_apos_5_quedas_seguidas(self, diaria, curvas, huawei, hoje, limite):
        import requests
        diaria.side_effect = requests.Timeout('demorou')
        imp = self.pedir()
        for _ in range(5):
            ImportacaoHistorico.objects.update(tentar_apos=None)
            with self.assertLogs('coletor', level='WARNING'):
                processar_fila(self.clientes, prazo=1, relogio=relogio_parado)
        imp.refresh_from_db()
        self.assertEqual(imp.status, 'erro')
        self.assertIn('Plataforma indisponível', imp.falhas[0])

    def test_usina_apagada_no_meio(self, diaria, curvas, huawei, hoje, limite):
        imp = self.pedir()
        self.fox.desativar()
        imp.usina.refresh_from_db()
        with self.assertLogs('coletor', level='ERROR'):
            executar_passo(imp, self.clientes)
        self.assertEqual(imp.status, 'erro')
        diaria.assert_not_called()


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


class TempoLivreTests(TestCase):
    """O tempo real tem prioridade: a fila só usa o tempo que sobra até o próximo ciclo."""

    @patch('integracoes.management.commands.coletar.time')
    @patch('integracoes.management.commands.coletar.processar_fila')
    def test_fila_recebe_prazo_antes_do_proximo_ciclo_e_sem_trabalho_espera(self, fila, relogio):
        from integracoes.management.commands.coletar import FOLGA, Command
        agora = [0.0]
        relogio.monotonic.side_effect = lambda: agora[0]
        relogio.sleep.side_effect = lambda s: agora.__setitem__(0, agora[0] + s)
        fila.return_value = 0                          # fila vazia

        Command.tempo_livre(Clientes(), proximo_ciclo=30)

        self.assertEqual(fila.call_args.kwargs['prazo'], 30 - FOLGA)
        self.assertEqual([c.args[0] for c in relogio.sleep.call_args_list], [10, 10, 10])   # olha a fila a cada 10 s
        self.assertEqual(agora[0], 30)                 # devolve na hora do tempo real
