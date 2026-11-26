"""Testes da coleta FoxESS com respostas simuladas no formato REAL da API (sem rede)."""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from monitoramento.models import GeracaoDiaria, Leitura
from usinas.models import Fabricante, Inversor, Plataforma, Status, Usina

from .coleta import (
    arredondar_5min, atualizar_tempo_real, horario_foxess, importar_curvas, importar_geracao_diaria,
)

SP = ZoneInfo('America/Sao_Paulo')


class HorarioTests(SimpleTestCase):
    def test_le_o_formato_da_foxess(self):
        self.assertEqual(horario_foxess('2026-11-09 10:04:58 BRT-0300'), datetime(2026, 11, 9, 10, 4, 58, tzinfo=SP))
        self.assertIsNone(horario_foxess(None))
        self.assertIsNone(horario_foxess('lixo'))

    def test_amostra_por_bloco_usa_a_real_mais_proxima(self):
        from .coleta import amostra_por_bloco
        base = datetime(2026, 11, 14, 6, 0, tzinfo=SP)
        pontos = [(base.replace(minute=28, second=40), 5.0), (base.replace(minute=32, second=10), 6.2),
                  (base.replace(minute=35, second=2), 7.0)]
        self.assertEqual(amostra_por_bloco(pontos), {
            base.replace(minute=30): 5.0,     # duas no bloco: fica a mais próxima (nunca soma)
            base.replace(minute=35): 7.0,
        })

    def test_arredonda_para_5_minutos(self):
        base = datetime(2026, 11, 9, 10, 0, tzinfo=SP)
        casos = {(4, 58): (10, 5), (20, 0): (10, 20), (22, 10): (10, 20), (23, 0): (10, 25), (57, 40): (11, 0)}
        for (m, s), (hh, mm) in casos.items():
            self.assertEqual(arredondar_5min(base.replace(minute=m, second=s)), base.replace(hour=hh, minute=mm))


class ColetaBase(TestCase):
    def setUp(self):
        self.usina = Usina.objects.create(plataforma=Plataforma.FOXESS, fabricante=Fabricante.WEG,
                                          id_externo='st-1', nome='UFV Teste', potencia_kwp=100)
        Inversor.objects.create(usina=self.usina, numero_serie='SN-A')
        Inversor.objects.create(usina=self.usina, numero_serie='SN-B')
        self.api = MagicMock()


class GeracaoDiariaTests(ColetaBase):
    def test_soma_inversores_ignora_futuro_e_zeros_iniciais(self):
        hoje = timezone.localdate()
        dias_no_mes = 31
        # Mês atual: dia 1 sem geração (usina ainda não existia), depois 10 kWh/dia por inversor
        valores = [0.0] + [10.0] * (dias_no_mes - 1)
        self.api.relatorio_mensal.side_effect = lambda sn, ano, mes: (
            [{'variable': 'generation', 'unit': 'kWh', 'values': valores}] if (ano, mes) == (hoje.year, hoje.month)
            else [{'variable': 'generation', 'unit': 'kWh', 'values': [0.0] * 31}])

        inicio = date(hoje.year - (hoje.month == 1), (hoje.month - 2) % 12 + 1, 1)   # mês anterior
        importar_geracao_diaria(self.usina, inicio, hoje, api=self.api)

        if hoje.day == 1:
            self.assertFalse(GeracaoDiaria.objects.exists())
            return
        datas = list(GeracaoDiaria.objects.order_by('data').values_list('data', 'energia_kwh'))
        self.assertEqual(datas[0][0], hoje.replace(day=2))       # zeros iniciais ignorados
        self.assertEqual(datas[-1][0], hoje)                      # nada no futuro
        self.assertEqual(float(datas[0][1]), 20.0)                # 2 inversores somados

    def test_repetir_nao_duplica(self):
        hoje = timezone.localdate()
        self.api.relatorio_mensal.return_value = [{'variable': 'generation', 'values': [5.0] * 31}]
        importar_geracao_diaria(self.usina, hoje.replace(day=1), hoje, api=self.api)
        importar_geracao_diaria(self.usina, hoje.replace(day=1), hoje, api=self.api)
        self.assertEqual(GeracaoDiaria.objects.count(), hoje.day)


class CurvasTests(ColetaBase):
    def resposta(self, dia: date, minutos_segundos, kw):
        pontos = [{'time': f'{dia:%Y-%m-%d} 10:{m:02d}:{s:02d} BRT-0300', 'value': kw} for m, s in minutos_segundos]
        return [{'deviceSN': 'x', 'datas': [{'variable': 'generationPower', 'unit': 'kW', 'data': pontos}]}]

    def test_soma_inversores_no_mesmo_bloco_de_5_min(self):
        hoje = timezone.localdate()
        # SN-A marca 10:04:58 e SN-B 10:05:03 -> mesmo bloco 10:05
        self.api.historico.side_effect = lambda sn, ini, fim: (
            self.resposta(ini.date(), [(4, 58)] if sn == 'SN-A' else [(5, 3)], 10.0 if sn == 'SN-A' else 5.0)
            if ini.date() == hoje else [])

        importar_curvas(self.usina, hoje, hoje, api=self.api)
        leitura = Leitura.objects.get()
        self.assertEqual(leitura.data_hora, datetime(hoje.year, hoje.month, hoje.day, 10, 5, tzinfo=SP))
        self.assertEqual(leitura.potencia_kw, 15.0)

    def pontos_reais(self, dia: date, amostras):
        """amostras: [(minuto, segundo, kW), ...] às 10h — formato real da FoxESS."""
        dados = [{'time': f'{dia:%Y-%m-%d} 10:{m:02d}:{s:02d} BRT-0300', 'value': kw} for m, s, kw in amostras]
        return [{'deviceSN': 'x', 'datas': [{'variable': 'generationPower', 'unit': 'kW', 'data': dados}]}]

    def test_duas_amostras_do_mesmo_inversor_no_bloco_fica_a_real_mais_proxima(self):
        # Caso real (14/11): 2 amostras do MESMO inversor no bloco das 10:30 eram somadas (valor dobrado)
        hoje = timezone.localdate()
        self.api.historico.side_effect = lambda sn, ini, fim: (
            self.pontos_reais(hoje, [(28, 40, 5.0), (32, 10, 6.2)]) if sn == 'SN-A' else [])
        importar_curvas(self.usina, hoje, hoje, api=self.api)
        leitura = Leitura.objects.get()
        self.assertEqual(leitura.data_hora, datetime(hoje.year, hoje.month, hoje.day, 10, 30, tzinfo=SP))
        self.assertEqual(leitura.potencia_kw, 5.0)   # 10:28:40 está mais perto das 10:30 (nem 11,2 nem média)

    def test_importacao_substitui_o_valor_do_tempo_real(self):
        hoje = timezone.localdate()
        bloco = datetime(hoje.year, hoje.month, hoje.day, 10, 5, tzinfo=SP)
        Leitura.objects.create(usina=self.usina, data_hora=bloco, potencia_kw=99.0)   # veio do tempo real
        self.api.historico.side_effect = lambda sn, ini, fim: (
            self.pontos_reais(hoje, [(4, 58, 44.0)]) if sn == 'SN-A' else [])
        importar_curvas(self.usina, hoje, hoje, api=self.api)
        self.assertEqual(Leitura.objects.get(data_hora=bloco).potencia_kw, 44.0)   # o importado tem prioridade

    def test_repetir_nao_duplica(self):
        hoje = timezone.localdate()
        self.api.historico.side_effect = lambda sn, ini, fim: self.resposta(ini.date(), [(0, 0), (5, 0)], 1.0)
        importar_curvas(self.usina, hoje - timedelta(days=1), hoje, api=self.api)
        importar_curvas(self.usina, hoje - timedelta(days=1), hoje, api=self.api)
        self.assertEqual(Leitura.objects.count(), 4)   # 2 dias × 2 blocos
        self.assertTrue(Leitura.objects.filter(data_hora__date=hoje).exists())


class TempoRealTests(ColetaBase):
    def test_atualiza_inversores_usina_leitura_e_dia(self):
        agora = timezone.localtime().replace(second=0, microsecond=0)
        texto = agora.strftime('%Y-%m-%d %H:%M:%S BRT-0300')

        def item(sn, kw, hoje_kwh, estado):
            return {'deviceSN': sn, 'time': texto, 'datas': [
                {'variable': 'generationPower', 'value': kw},
                {'variable': 'todayYield', 'value': hoje_kwh},
                {'variable': 'runningState', 'value': str(estado)},
            ]}
        self.api.tempo_real.return_value = [item('SN-A', 30.0, 100.0, 163), item('SN-B', 0.0, 50.0, 165)]

        rel = atualizar_tempo_real(api=self.api)

        self.assertEqual(rel.inversores, 2)
        a, b = Inversor.objects.get(numero_serie='SN-A'), Inversor.objects.get(numero_serie='SN-B')
        self.assertEqual((a.status, float(a.potencia_atual_kw)), (Status.ONLINE, 30.0))
        self.assertEqual(b.status, Status.ALERTA)                       # 165 = falha
        self.usina.refresh_from_db()
        self.assertEqual(self.usina.status, Status.ALERTA)
        self.assertEqual(Leitura.objects.get().potencia_kw, 30.0)
        self.assertEqual(float(GeracaoDiaria.objects.get(data=agora.date()).energia_kwh), 150.0)

    def desligado_as(self, hora: int):
        momento = datetime.combine(timezone.localdate(), datetime.min.time(), SP).replace(hour=hora)
        texto = momento.strftime('%Y-%m-%d %H:%M:%S BRT-0300')
        self.api.tempo_real.return_value = [
            {'deviceSN': sn, 'time': texto, 'datas': [{'variable': 'generationPower', 'value': 0.0},
                                                      {'variable': 'runningState', 'value': '170'}]}
            for sn in ('SN-A', 'SN-B')]
        with patch('integracoes.coleta.timezone.now', return_value=momento + timedelta(minutes=2)):
            atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()
        return self.usina.status

    def test_sem_geracao_a_noite_e_sem_sol(self):
        self.assertEqual(self.desligado_as(22), Status.NOITE)
        self.assertEqual(self.desligado_as(5), Status.NOITE)

    def test_comunicando_sem_gerar_em_pleno_dia_e_falha_nao_offline(self):
        self.assertEqual(self.desligado_as(11), Status.ALERTA)

    def test_comunicando_sem_gerar_com_pouco_sol_e_sem_sol(self):
        self.assertEqual(self.desligado_as(7), Status.NOITE)     # começo da manhã
        self.assertEqual(self.desligado_as(17), Status.NOITE)    # fim da tarde

    def test_aguardando_rede_em_pleno_dia_e_falha(self):
        momento = datetime.combine(timezone.localdate(), datetime.min.time(), SP).replace(hour=12)
        texto = momento.strftime('%Y-%m-%d %H:%M:%S BRT-0300')
        self.api.tempo_real.return_value = [   # 161 = aguardando, 162 = verificando (tentando religar após a falha)
            {'deviceSN': 'SN-A', 'time': texto, 'datas': [{'variable': 'generationPower', 'value': 0.0},
                                                          {'variable': 'runningState', 'value': '161'}]},
            {'deviceSN': 'SN-B', 'time': texto, 'datas': [{'variable': 'generationPower', 'value': 0.0},
                                                          {'variable': 'runningState', 'value': '162'}]}]
        with patch('integracoes.coleta.timezone.now', return_value=momento + timedelta(minutes=2)):
            atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()
        self.assertEqual(self.usina.status, Status.ALERTA)

    def test_em_falha_e_perdeu_comunicacao_continua_falha_ate_o_fim_do_dia(self):
        hoje = datetime.combine(timezone.localdate(), datetime.min.time(), SP)
        Inversor.objects.update(status=Status.ALERTA, ultima_leitura=hoje.replace(hour=10))
        self.api.tempo_real.return_value = []                     # ninguém responde
        with patch('integracoes.coleta.timezone.now', return_value=hoje.replace(hour=13)):
            atualizar_tempo_real(api=self.api)
        self.assertEqual(set(Inversor.objects.values_list('status', flat=True)), {Status.ALERTA})
        # no dia seguinte, ainda sem comunicação: aí sim offline
        with patch('integracoes.coleta.timezone.now', return_value=hoje.replace(hour=13) + timedelta(days=1)):
            atualizar_tempo_real(api=self.api)
        self.assertEqual(set(Inversor.objects.values_list('status', flat=True)), {Status.OFFLINE})

    def test_falha_a_noite_continua_alerta(self):
        momento = datetime.combine(timezone.localdate(), datetime.min.time(), SP).replace(hour=22)
        texto = momento.strftime('%Y-%m-%d %H:%M:%S BRT-0300')
        self.api.tempo_real.return_value = [
            {'deviceSN': 'SN-A', 'time': texto, 'datas': [{'variable': 'runningState', 'value': '165'}]},
            {'deviceSN': 'SN-B', 'time': texto, 'datas': [{'variable': 'runningState', 'value': '170'}]},
        ]
        with patch('integracoes.coleta.timezone.now', return_value=momento + timedelta(minutes=2)):
            atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()
        self.assertEqual(self.usina.status, Status.ALERTA)

    def ler_as(self, ultima_leitura: datetime, agora: datetime, kw=12.0):
        """FoxESS devolve a ÚLTIMA leitura guardada (que pode ser velha)."""
        texto = ultima_leitura.strftime('%Y-%m-%d %H:%M:%S BRT-0300')
        self.api.tempo_real.return_value = [
            {'deviceSN': sn, 'time': texto, 'datas': [{'variable': 'generationPower', 'value': kw},
                                                      {'variable': 'todayYield', 'value': 40.0},
                                                      {'variable': 'runningState', 'value': '163'}]}
            for sn in ('SN-A', 'SN-B')]
        with patch('integracoes.coleta.timezone.now', return_value=agora):
            atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()

    def test_leitura_velha_de_dia_vira_offline_e_zera_a_potencia(self):
        hoje = datetime.combine(timezone.localdate(), datetime.min.time(), SP)
        self.ler_as(hoje.replace(hour=11), hoje.replace(hour=13))       # parou às 11h; agora são 13h
        self.assertEqual(self.usina.status, Status.OFFLINE)
        inv = Inversor.objects.get(numero_serie='SN-A')
        self.assertEqual(float(inv.potencia_atual_kw), 0.0)              # não fica "gerando" congelado
        self.assertEqual(float(inv.geracao_hoje_kwh), 0.0)               # nunca leu hoje com sucesso

    def test_leitura_recente_continua_valendo(self):
        hoje = datetime.combine(timezone.localdate(), datetime.min.time(), SP)
        self.ler_as(hoje.replace(hour=11), hoje.replace(hour=11, minute=20))   # 20 min < 60 min
        self.assertEqual(self.usina.status, Status.ONLINE)
        self.assertEqual(Leitura.objects.get().potencia_kw, 24.0)

    def test_leitura_da_vespera_a_noite_e_sem_sol_e_nao_conta_hoje(self):
        hoje = datetime.combine(timezone.localdate(), datetime.min.time(), SP)
        self.ler_as(hoje.replace(hour=17, minute=50) - timedelta(days=1), hoje.replace(hour=5))
        self.assertEqual(self.usina.status, Status.NOITE)
        self.assertFalse(GeracaoDiaria.objects.filter(data=hoje.date()).exists())   # energia de ontem não vira hoje
        self.assertFalse(Leitura.objects.exists())

    def test_inversor_que_nao_responde_nao_soma_valor_antigo(self):
        hoje = datetime.combine(timezone.localdate(), datetime.min.time(), SP)
        Inversor.objects.filter(numero_serie='SN-B').update(potencia_atual_kw=50, status=Status.ONLINE,
                                                            ultima_leitura=hoje.replace(hour=9))
        texto = hoje.replace(hour=12).strftime('%Y-%m-%d %H:%M:%S BRT-0300')
        self.api.tempo_real.return_value = [{'deviceSN': 'SN-A', 'time': texto, 'datas': [
            {'variable': 'generationPower', 'value': 10.0}, {'variable': 'runningState', 'value': '163'}]}]
        with patch('integracoes.coleta.timezone.now', return_value=hoje.replace(hour=12, minute=2)):
            atualizar_tempo_real(api=self.api)
        self.assertEqual(Leitura.objects.get().potencia_kw, 10.0)        # os 50 kW antigos do SN-B não entram
        self.assertEqual(Inversor.objects.get(numero_serie='SN-B').status, Status.OFFLINE)


class FalhaParcialTests(ColetaBase):
    """Inversor com erro não pode virar soma parcial gravada por cima do valor certo."""

    def test_mes_com_inversor_falhando_nao_sobrescreve(self):
        from .foxess import FoxESSErro
        ontem = timezone.localdate() - timedelta(days=1)
        GeracaoDiaria.objects.create(usina=self.usina, data=ontem, energia_kwh=300)

        def relatorio(sn, ano, mes):
            if sn == 'SN-B':
                raise FoxESSErro('/report', 40400)
            return [{'variable': 'generation', 'values': [100.0] * 31}]
        self.api.relatorio_mensal.side_effect = relatorio
        rel = importar_geracao_diaria(self.usina, ontem, ontem, api=self.api)
        self.assertTrue(rel.falhas)
        self.assertEqual(float(GeracaoDiaria.objects.get(data=ontem).energia_kwh), 300.0)   # intacto

    def test_dias_parados_depois_da_primeira_geracao_ficam_como_zero(self):
        hoje = timezone.localdate()
        inicio = hoje.replace(day=1) - timedelta(days=40)
        GeracaoDiaria.objects.create(usina=self.usina, data=inicio, energia_kwh=10)   # já gerava antes
        self.api.relatorio_mensal.return_value = [{'variable': 'generation', 'values': [0.0] * 31}]
        primeiro = hoje.replace(day=1)
        importar_geracao_diaria(self.usina, primeiro, primeiro, api=self.api)
        self.assertEqual(float(GeracaoDiaria.objects.get(data=primeiro).energia_kwh), 0.0)


class InicioOperacaoTests(ColetaBase):
    def test_importacao_comeca_no_inicio_da_operacao_e_grava_zeros_depois(self):
        hoje = timezone.localdate()
        self.usina.inicio_operacao = hoje - timedelta(days=2)
        self.usina.save()
        self.api.relatorio_mensal.return_value = [{'variable': 'generation', 'values': [0.0] * 31}]
        importar_geracao_diaria(self.usina, hoje - timedelta(days=365), hoje, api=self.api)
        datas = sorted(g.data for g in GeracaoDiaria.objects.all())
        self.assertEqual(datas[0], hoje - timedelta(days=2))         # nada antes do início
        self.assertEqual(len(datas), 3)                              # zeros depois do início ficam (dia parado)
        meses = {(c.args[1], c.args[2]) for c in self.api.relatorio_mensal.call_args_list}
        self.assertLessEqual(len(meses), 2)                          # não pediu 12 meses à plataforma

    def test_curvas_tambem_comecam_no_inicio(self):
        hoje = timezone.localdate()
        self.usina.inicio_operacao = hoje
        self.usina.save()
        self.api.historico.return_value = []
        importar_curvas(self.usina, hoje - timedelta(days=30), hoje, api=self.api)
        self.assertEqual(self.api.historico.call_count, 2)          # 1 dia × 2 inversores


class DiasSemGeracaoTests(ColetaBase):
    def test_dia_todo_zerado_nao_vira_curva(self):
        hoje = timezone.localdate()

        def historico(sn, ini, fim):
            valor = 0.0 if ini.date() < hoje else 2.0          # antes de hoje a usina não operava
            return [{'datas': [{'variable': 'generationPower', 'data': [
                {'time': ini.strftime('%Y-%m-%d 10:00:00 BRT-0300'), 'value': valor},
                {'time': ini.strftime('%Y-%m-%d 10:05:00 BRT-0300'), 'value': valor}]}]}]
        self.api.historico.side_effect = historico
        importar_curvas(self.usina, hoje - timedelta(days=6), hoje, api=self.api)
        self.assertEqual({l.data_hora.astimezone(SP).date() for l in Leitura.objects.all()}, {hoje})


class PeriodoECoberturaTests(ColetaBase):
    def test_periodo_respeita_inicio_e_fim(self):
        hoje = timezone.localdate()
        self.api.relatorio_mensal.return_value = [{'variable': 'generation', 'values': [5.0] * 31}]
        inicio = hoje - timedelta(days=3)
        importar_geracao_diaria(self.usina, inicio, hoje - timedelta(days=1), api=self.api)
        datas = set(GeracaoDiaria.objects.values_list('data', flat=True))
        self.assertEqual(datas, {inicio, inicio + timedelta(days=1), inicio + timedelta(days=2)})

    def test_curvas_nao_passam_do_limite_de_retencao(self):
        from .coleta import limite_curvas
        self.api.historico.return_value = []
        antigo = limite_curvas() - timedelta(days=10)
        importar_curvas(self.usina, antigo, limite_curvas(), api=self.api)
        dias_pedidos = {c.args[1].date() for c in self.api.historico.call_args_list}
        self.assertEqual(min(dias_pedidos), limite_curvas())   # não pede dias que o banco não guarda

    def test_cobertura(self):
        from .coleta import cobertura
        hoje = timezone.localdate()
        GeracaoDiaria.objects.create(usina=self.usina, data=hoje - timedelta(days=5), energia_kwh=1)
        GeracaoDiaria.objects.create(usina=self.usina, data=hoje, energia_kwh=1)
        Leitura.objects.create(usina=self.usina, data_hora=timezone.now(), potencia_kw=1)
        c = cobertura(self.usina)
        self.assertEqual((c['energia_diaria']['inicio'], c['energia_diaria']['dias']), (hoje - timedelta(days=5), 2))
        self.assertEqual((c['curvas']['dias'], c['inversores']), (1, 2))
