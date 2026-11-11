"""Testes da coleta FoxESS com respostas simuladas no formato REAL da API (sem rede)."""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock
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
        texto = timezone.localdate().strftime(f'%Y-%m-%d {hora:02d}:00:00 BRT-0300')
        self.api.tempo_real.return_value = [
            {'deviceSN': sn, 'time': texto, 'datas': [{'variable': 'generationPower', 'value': 0.0},
                                                      {'variable': 'runningState', 'value': '170'}]}
            for sn in ('SN-A', 'SN-B')]
        atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()
        return self.usina.status

    def test_sem_geracao_a_noite_e_sem_sol(self):
        self.assertEqual(self.desligado_as(22), Status.NOITE)
        self.assertEqual(self.desligado_as(5), Status.NOITE)

    def test_sem_geracao_de_dia_e_offline(self):
        self.assertEqual(self.desligado_as(11), Status.OFFLINE)

    def test_falha_a_noite_continua_alerta(self):
        texto = timezone.localdate().strftime('%Y-%m-%d 22:00:00 BRT-0300')
        self.api.tempo_real.return_value = [
            {'deviceSN': 'SN-A', 'time': texto, 'datas': [{'variable': 'runningState', 'value': '165'}]},
            {'deviceSN': 'SN-B', 'time': texto, 'datas': [{'variable': 'runningState', 'value': '170'}]},
        ]
        atualizar_tempo_real(api=self.api)
        self.usina.refresh_from_db()
        self.assertEqual(self.usina.status, Status.ALERTA)


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
