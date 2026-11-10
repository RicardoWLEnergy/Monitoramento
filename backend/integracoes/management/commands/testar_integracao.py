"""
Teste de conexão com a API de um fabricante. SÓ LEITURA: não grava nada no banco.

Uso:
    python manage.py testar_integracao foxess
    python manage.py testar_integracao foxess --usina "Nome da usina"
    python manage.py testar_integracao foxess --usina "Nome" --bruto   (mostra o JSON original)
    python manage.py testar_integracao huawei --usina "Nome" --bruto
"""
import json
from collections import Counter
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from integracoes import huawei
from integracoes.foxess import ESTADOS, FoxESSCliente, FoxESSErro


class Command(BaseCommand):
    help = 'Testa a conexão com a API de um fabricante (somente leitura).'

    def add_arguments(self, parser):
        parser.add_argument('fabricante', choices=['foxess', 'huawei'])
        parser.add_argument('--usina', help='Parte do nome da usina teste (padrão: a primeira da lista).')
        parser.add_argument('--bruto', action='store_true', help='Mostra também o JSON original das respostas.')

    def handle(self, *args, **opcoes):
        try:
            if opcoes['fabricante'] == 'huawei':
                self.testar_huawei(opcoes['usina'], opcoes['bruto'])
            else:
                self.testar_foxess(opcoes['usina'], opcoes['bruto'])
        except (FoxESSErro, huawei.HuaweiErro, ValueError) as erro:
            raise CommandError(str(erro)) from erro

    # ------------------------------------------------------------------
    def titulo(self, texto):
        self.stdout.write('\n' + self.style.MIGRATE_HEADING(f'== {texto} =='))

    def bruto(self, ativo, dados):
        if ativo:
            self.stdout.write(json.dumps(dados, ensure_ascii=False, indent=2, default=str))

    def testar_foxess(self, filtro_usina: str | None, mostrar_bruto: bool):
        from django.conf import settings
        cliente = FoxESSCliente(settings.FOXESS_API_URL, settings.FOXESS_API_KEY)

        # 1) Autenticação + cota
        self.titulo('1. Autenticação')
        cota_inicial = cliente.cota()
        self.stdout.write(self.style.SUCCESS('API key aceita.'))
        self.stdout.write(f"Cota de chamadas hoje: {cota_inicial.get('remaining')} restantes de {cota_inicial.get('total')}")

        # 2) Usinas visíveis
        self.titulo('2. Usinas que esta chave enxerga')
        usinas = cliente.listar_usinas()
        self.stdout.write(f'Total: {len(usinas)} usina(s)')
        for u in usinas[:10]:
            self.stdout.write(f"  - {u.get('name')}  (id {u.get('stationID')}, fuso {u.get('ianaTimezone')})")
        if len(usinas) > 10:
            self.stdout.write(f'  ... e mais {len(usinas) - 10}')
        if not usinas:
            raise CommandError('Nenhuma usina visível para esta chave.')

        # 3) Inversores visíveis
        self.titulo('3. Inversores que esta chave enxerga')
        inversores = cliente.listar_inversores()
        status = Counter({1: 'online', 2: 'falha', 3: 'offline'}.get(i.get('status'), '?') for i in inversores)
        modelos = Counter(i.get('deviceType') for i in inversores)
        self.stdout.write(f'Total: {len(inversores)} inversor(es) — ' + ', '.join(f'{n} {s}' for s, n in status.items()))
        self.stdout.write('Modelos: ' + ', '.join(f'{m} ({n})' for m, n in modelos.most_common(8)))

        # 4) Usina teste
        if filtro_usina:
            escolhidas = [u for u in usinas if filtro_usina.lower() in (u.get('name') or '').lower()]
            if not escolhidas:
                raise CommandError(f'Nenhuma usina com "{filtro_usina}" no nome.')
            usina = escolhidas[0]
        else:
            usina = usinas[0]

        self.titulo(f"4. Usina teste: {usina.get('name')}")
        detalhe = cliente.detalhe_usina(usina['stationID'])
        self.bruto(mostrar_bruto, detalhe)
        self.stdout.write(f"Cidade: {detalhe.get('city')} / {detalhe.get('country')}")
        self.stdout.write(f"Endereço: {detalhe.get('address')}")
        self.stdout.write(f"Capacidade cadastrada: {detalhe.get('capacity')} kW")
        self.stdout.write(f"Fuso: {detalhe.get('timezone') or usina.get('ianaTimezone')}")

        sns = [i['deviceSN'] for i in inversores if i.get('stationID') == usina['stationID']]
        if not sns:
            sns = [m['deviceSN'] for m in detalhe.get('modules') or [] if m.get('deviceSN')]
        self.stdout.write(f'Inversores: {", ".join(sns) or "nenhum"}')
        if not sns:
            return

        # 5) Tempo real
        self.titulo('5. Tempo real (por inversor)')
        tempo_real = cliente.tempo_real(sns)
        self.bruto(mostrar_bruto, tempo_real)
        potencia_total = 0.0
        for inv in tempo_real:
            valores = {d['variable']: d for d in inv.get('datas', [])}
            self.stdout.write(f"\n  Inversor {inv.get('deviceSN')}")
            for var, d in valores.items():
                extra = ''
                if var == 'runningState':
                    extra = f"  ({ESTADOS.get(int(d.get('value') or 0), 'desconhecido')})"
                self.stdout.write(f"    {d.get('name') or var:<28} {d.get('value')} {d.get('unit') or ''}{extra}")
            if 'generationPower' in valores:
                potencia_total += float(valores['generationPower'].get('value') or 0)
                self.stdout.write(f"    horário da leitura: {valores['generationPower'].get('time')}")
        self.stdout.write(self.style.SUCCESS(f'\n  Potência da usina agora (soma): {potencia_total:.3f} kW'))

        # 6) Energia
        self.titulo('6. Energia (kWh)')
        for sn in sns:
            g = cliente.geracao(sn)
            self.bruto(mostrar_bruto, g)
            self.stdout.write(f"  {sn}: hoje {g.get('today')} | mês {g.get('month')} | total {g.get('cumulative')}")

        # 7) Consumo de cota do teste
        cota_final = cliente.cota()
        gastas = (cota_inicial.get('remaining') or 0) - (cota_final.get('remaining') or 0)
        self.titulo('Resumo')
        self.stdout.write(f'Chamadas consumidas por este teste: {gastas}')
        self.stdout.write('Confira os números acima com o portal da FoxESS.')

    # ------------------------------------------------------------------
    # Huawei FusionSolar
    # ------------------------------------------------------------------
    def testar_huawei(self, filtro_usina: str | None, mostrar_bruto: bool):
        api = huawei.HuaweiCliente(settings.HUAWEI_API_URL, settings.HUAWEI_USUARIO, settings.HUAWEI_SENHA)

        # 1) Login
        self.titulo('1. Login')
        self.stdout.write(f'Endereço: {settings.HUAWEI_API_URL}')
        api.login()
        self.stdout.write(self.style.SUCCESS('Login aceito (token recebido).'))

        # 2) Usinas
        self.titulo('2. Usinas que esta conta enxerga')
        usinas = api.listar_usinas()
        self.stdout.write(f'Total: {len(usinas)} usina(s)')
        for u in usinas[:10]:
            self.stdout.write(f"  - {u.get('plantName')}  (código {u.get('plantCode')}, capacidade {u.get('capacity')})")
        if len(usinas) > 10:
            self.stdout.write(f'  ... e mais {len(usinas) - 10}')
        if not usinas:
            raise CommandError('Nenhuma usina visível. Confira se a conta Northbound tem as usinas vinculadas.')

        if filtro_usina:
            escolhidas = [u for u in usinas if filtro_usina.lower() in (u.get('plantName') or '').lower()]
            if not escolhidas:
                raise CommandError(f'Nenhuma usina com "{filtro_usina}" no nome.')
            usina = escolhidas[0]
        else:
            usina = usinas[0]
        codigo = usina['plantCode']

        # 3) Dados da usina
        self.titulo(f"3. Usina teste: {usina.get('plantName')}")
        self.bruto(mostrar_bruto, usina)
        self.stdout.write(f"Endereço: {usina.get('plantAddress')}")
        self.stdout.write(f"Capacidade: {usina.get('capacity')}  (confirmar se é kWp ou MW)")
        self.stdout.write(f"Coordenadas: lat {usina.get('latitude')} / lon {usina.get('longitude')}  (confirmar a ordem)")

        kpi = api.tempo_real_usinas([codigo])
        self.bruto(mostrar_bruto, kpi)
        if kpi:
            k = kpi[0].get('dataItemMap') or {}
            saude = huawei.SAUDE.get(int(k.get('real_health_state') or 0), '?')
            self.stdout.write(f"Energia: hoje {k.get('day_power')} | mês {k.get('month_power')} | total {k.get('total_power')} kWh")
            self.stdout.write(f'Saúde: {saude}')

        # 4) Dispositivos
        self.titulo('4. Dispositivos da usina')
        dispositivos = api.listar_dispositivos([codigo])
        self.bruto(mostrar_bruto, dispositivos)
        for d in dispositivos:
            self.stdout.write(f"  - tipo {d.get('devTypeId')}: {d.get('devName')} | SN {d.get('esnCode')} | "
                              f"modelo {d.get('invType')} | id {d.get('id')}")
        inversores = [d for d in dispositivos if d.get('devTypeId') in huawei.TIPOS_INVERSOR]
        if not inversores:
            self.stdout.write(self.style.WARNING('Nenhum inversor (tipo 1 ou 38) visível nesta usina.'))
            return

        # 5) Tempo real dos inversores
        self.titulo('5. Tempo real dos inversores')
        for tipo in {d['devTypeId'] for d in inversores}:
            ids = [d['id'] for d in inversores if d['devTypeId'] == tipo]
            dados = api.tempo_real_dispositivos(ids, tipo)
            self.bruto(mostrar_bruto, dados)
            for item in dados:
                m = item.get('dataItemMap') or {}
                estado = huawei.ESTADOS.get(int(float(m.get('inverter_state') or 0)), m.get('inverter_state'))
                self.stdout.write(f"  devId {item.get('devId')}: potência {m.get('active_power')} "
                                  f"(confirmar kW ou W) | hoje {m.get('day_cap')} kWh | estado {estado}")

        # 6) Energia diária do mês
        self.titulo('6. Energia diária do mês (getKpiStationDay)')
        agora = timezone.localtime()
        dias = api.kpi_diario([codigo], agora.replace(day=1, hour=12))
        self.bruto(mostrar_bruto, dias[:3])
        for d in dias[-5:]:
            momento = datetime.fromtimestamp(int(d.get('collectTime', 0)) / 1000, tz=timezone.get_current_timezone())
            self.stdout.write(f"  {momento:%d/%m/%Y}: {(d.get('dataItemMap') or {}).get('inverter_power')} kWh")

        # 7) Curva de 5 min (hoje)
        self.titulo('7. Curva de 5 min de hoje (getDevHistoryKpi)')
        inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
        tipo = inversores[0]['devTypeId']
        ids = [d['id'] for d in inversores if d['devTypeId'] == tipo][:10]
        pontos = api.historico_dispositivos(ids, tipo, inicio, agora)
        self.stdout.write(f'Registros recebidos: {len(pontos)}')
        self.bruto(mostrar_bruto, pontos[:3])
        for p in pontos[-3:]:
            momento = datetime.fromtimestamp(int(p.get('collectTime', 0)) / 1000, tz=timezone.get_current_timezone())
            self.stdout.write(f"  {momento:%H:%M} devId {p.get('devId')}: {(p.get('dataItemMap') or {}).get('active_power')}")

        self.titulo('Resumo')
        self.stdout.write(f'Chamadas feitas: {api.chamadas}')
        self.stdout.write('Confira com o portal FusionSolar: energia de hoje, potência atual e capacidade.')
