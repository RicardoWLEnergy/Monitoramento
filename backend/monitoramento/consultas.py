"""
Consultas de geração usadas pela API (lista de usinas, detalhe e dashboard).
Recebem sempre um conjunto de usinas JÁ filtrado pelo perfil do usuário.
"""
import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import DateTimeField, F, FloatField, Func, Min, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Cast, Coalesce, TruncMonth
from django.utils import timezone

from usinas.models import GeracaoEsperada, Inversor, Status

from .models import Alerta, GeracaoDiaria, Leitura

MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']


def _primeiro_dia(d: date, meses_atras: int = 0) -> date:
    total = d.year * 12 + d.month - 1 - meses_atras
    return date(total // 12, total % 12 + 1, 1)


def fracao_do_mes(hoje: date) -> float:
    """Parte do mês já passada, contando o dia de hoje (ex.: dia 15 de um mês de 30 dias = 0,5).
    Base do "esperado até hoje": no meio do mês compara com metade do esperado do mês, não com o mês inteiro."""
    return hoje.day / calendar.monthrange(hoje.year, hoje.month)[1]


def dias_operando(mes_inicio: date, ate: date, inicio_operacao: date | None) -> int:
    """Dias do mês (de mes_inicio até `ate`, contando os dois) em que a usina já estava operando."""
    if not inicio_operacao:
        return 0
    return max(0, (ate - max(mes_inicio, inicio_operacao)).days + 1)


def esperado_proporcional(esperado_mes: float, mes_inicio: date, ate: date, inicio_operacao: date | None) -> float:
    """
    Esperado do mês proporcional aos dias em que a usina já operava. Ex.: esperado de 900 kWh num mês de 30 dias,
    usina ligada no dia 18, hoje dia 20 → 900 × 3/30 = 90 kWh (os dias antes de ligar não contam).
    """
    dias_mes = calendar.monthrange(mes_inicio.year, mes_inicio.month)[1]
    return float(esperado_mes or 0) * dias_operando(mes_inicio, ate, inicio_operacao) / dias_mes


def inicio_operacao_por_usina(usinas) -> dict[int, date]:
    """Início da operação de cada usina: a data cadastrada (vinda da plataforma); sem ela, o 1º dia com geração."""
    primeira = dict(GeracaoDiaria.objects.filter(usina__in=usinas, energia_kwh__gt=0)
                    .values('usina').annotate(p=Min('data')).values_list('usina', 'p'))
    cadastrada = dict(usinas.model.objects.filter(pk__in=usinas.values('pk'), inicio_operacao__isnull=False)
                      .values_list('pk', 'inicio_operacao')) if hasattr(usinas, 'model') else {}
    return {**primeira, **cadastrada}


def esperado_ate_hoje(usina, hoje: date | None = None) -> float:
    """Esperado do mês até hoje para uma usina vinda de anotar_usinas (desde o início da operação)."""
    hoje = hoje or timezone.localdate()
    inicio = getattr(usina, 'inicio_operacao', None) or getattr(usina, 'primeira_geracao', None)
    return esperado_proporcional(getattr(usina, 'esperado_mes_kwh', 0), _primeiro_dia(hoje), hoje, inicio)


MAX_DIAS_PERIODO = 366


def ler_data(texto: str | None, padrao: date) -> date:
    """AAAA-MM-DD entre 2000 e 2100 (datas absurdas viram erro de formato, não erro do servidor)."""
    if not texto:
        return padrao
    try:
        dia = date.fromisoformat(texto)
    except (TypeError, ValueError):
        raise ValueError('Use datas no formato AAAA-MM-DD.') from None
    if not 2000 <= dia.year <= 2100:
        raise ValueError('Data fora do intervalo aceito.')
    return dia


def ler_periodo(params, hoje: date | None = None) -> tuple[date, date]:
    """?inicio=&fim= (AAAA-MM-DD). Padrão: últimos 30 dias; data futura vira hoje; até 1 ano. ValueError se inválido."""
    hoje = hoje or timezone.localdate()
    fim = min(ler_data(params.get('fim'), hoje), hoje)
    inicio = ler_data(params.get('inicio'), fim - timedelta(days=29))
    if inicio > fim:
        raise ValueError('A data inicial deve ser anterior à final.')
    if (fim - inicio).days + 1 > MAX_DIAS_PERIODO:
        raise ValueError('Escolha um período de até 1 ano.')
    return inicio, fim


def _soma(qs, campo: str):
    """Subconsulta: soma de `campo` por usina (evita duplicar linhas ao juntar várias tabelas)."""
    sub = qs.filter(usina=OuterRef('pk')).values('usina').annotate(t=Sum(campo)).values('t')
    return Coalesce(Cast(Subquery(sub), FloatField()), Value(0.0))


def anotar_usinas(usinas, hoje: date | None = None):
    """
    Acrescenta a cada usina: potência atual, geração de hoje, do mês, o esperado do mês e o 1º dia com geração
    (reserva do início da operação). O esperado ATÉ HOJE sai de esperado_ate_hoje(usina): só os dias já operando.
    """
    hoje = hoje or timezone.localdate()
    esperado_mes = _soma(GeracaoEsperada.objects.filter(mes=hoje.month), 'energia_kwh')
    primeira_geracao = (GeracaoDiaria.objects.filter(usina=OuterRef('pk'), energia_kwh__gt=0)
                        .order_by('data').values('data')[:1])
    return usinas.annotate(
        potencia_atual_kw=_soma(Inversor.objects.all(), 'potencia_atual_kw'),
        geracao_hoje_kwh=_soma(Inversor.objects.all(), 'geracao_hoje_kwh'),
        geracao_mes_kwh=_soma(GeracaoDiaria.objects.filter(data__gte=_primeiro_dia(hoje), data__lte=hoje), 'energia_kwh'),
        esperado_mes_kwh=esperado_mes,
        primeira_geracao=Subquery(primeira_geracao),   # reserva, se a usina não tiver o início da operação
    )


def _intervalo_do_dia(dia: date, fuso: str) -> tuple[datetime, datetime]:
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=ZoneInfo(fuso))
    return inicio, inicio + timedelta(days=1)


def curva_do_dia(usina, dia: date) -> list[dict]:
    """Potência ao longo do dia (no fuso da usina): [{'hora': '10:35', 'kw': 44.1}, ...]."""
    fuso = ZoneInfo(usina.fuso_horario)
    inicio, fim = _intervalo_do_dia(dia, usina.fuso_horario)
    leituras = Leitura.objects.filter(usina=usina, data_hora__gte=inicio, data_hora__lt=fim).order_by('data_hora')
    return [{'hora': l.data_hora.astimezone(fuso).strftime('%H:%M'), 'kw': round(l.potencia_kw, 3)} for l in leituras]


def geracao_por_dia(usinas, inicio: date, fim: date) -> list[dict]:
    """
    Energia de cada dia do período, somando as usinas, e o esperado do dia:
    [{'data': '2026-11-01', 'kwh': 288.4, 'esperado_kwh': 300.0}, ...].
    - Dia sem nenhum dado: kwh = None (não é zero).
    - Esperado do dia = esperado do mês ÷ dias do mês, só a partir do início da operação de cada usina
      (None sem geração esperada cadastrada ou antes de a usina ligar).
    """
    energia = dict(GeracaoDiaria.objects.filter(usina__in=usinas, data__gte=inicio, data__lte=fim)
                   .values('data').annotate(total=Sum('energia_kwh')).values_list('data', 'total'))
    inicio_op = inicio_operacao_por_usina(usinas)
    esperado = list(GeracaoEsperada.objects.filter(usina__in=usinas).values_list('usina_id', 'mes', 'energia_kwh'))

    def esperado_do_dia(d: date) -> float | None:
        """Soma das usinas que já operavam no dia (antes de ligar, a usina não tem esperado)."""
        total = sum(float(kwh) for u, m, kwh in esperado if m == d.month and inicio_op.get(u) and inicio_op[u] <= d)
        return round(total / calendar.monthrange(d.year, d.month)[1], 3) if total else None

    dias = (fim - inicio).days + 1
    return [
        {'data': d.isoformat(), 'kwh': round(float(energia[d]), 3) if d in energia else None,
         'esperado_kwh': esperado_do_dia(d)}
        for d in (inicio + timedelta(days=i) for i in range(dias))
    ]


def curva_da_carteira(usinas, dia: date) -> list[dict]:
    """Potência somada de várias usinas, em blocos de 5 min (fuso do sistema)."""
    fuso = ZoneInfo(settings.TIME_ZONE)
    inicio, fim = _intervalo_do_dia(dia, settings.TIME_ZONE)
    bloco = Func(Value(timedelta(minutes=5)), F('data_hora'), Value(inicio),
                 function='date_bin', output_field=DateTimeField())
    linhas = (Leitura.objects.filter(usina__in=usinas, data_hora__gte=inicio, data_hora__lt=fim)
              .annotate(bloco=bloco).values('bloco').annotate(kw=Sum('potencia_kw')).order_by('bloco'))
    return [{'hora': l['bloco'].astimezone(fuso).strftime('%H:%M'), 'kw': round(l['kw'], 3)} for l in linhas]


def geracao_mensal(usinas, meses: int = 12, hoje: date | None = None) -> list[dict]:
    """Últimos `meses` meses: gerado (soma dos dias) × esperado. O mês atual vem marcado como parcial,
    com o esperado até hoje. O esperado só conta a partir do início da operação de cada usina."""
    hoje = hoje or timezone.localdate()
    inicio = _primeiro_dia(hoje, meses - 1)

    gerado = {
        l['mes'].date() if hasattr(l['mes'], 'date') else l['mes']: float(l['total'] or 0)
        for l in GeracaoDiaria.objects.filter(usina__in=usinas, data__gte=inicio, data__lte=hoje)
        .annotate(mes=TruncMonth('data')).values('mes').annotate(total=Sum('energia_kwh'))
    }
    inicio_op = inicio_operacao_por_usina(usinas)
    esperado = list(GeracaoEsperada.objects.filter(usina__in=usinas).values_list('usina_id', 'mes', 'energia_kwh'))

    resultado = []
    for i in range(meses - 1, -1, -1):
        mes = _primeiro_dia(hoje, i)
        fim_mes = mes.replace(day=calendar.monthrange(mes.year, mes.month)[1])
        do_mes = [(u, float(kwh)) for u, m, kwh in esperado if m == mes.month]
        # Antes de a usina ligar não há esperado; no mês em que ligou, só os dias a partir dali
        esperado_mes = sum(esperado_proporcional(kwh, mes, fim_mes, inicio_op.get(u)) for u, kwh in do_mes)
        esperado_ate = sum(esperado_proporcional(kwh, mes, min(fim_mes, hoje), inicio_op.get(u)) for u, kwh in do_mes)
        resultado.append({
            'mes': mes.strftime('%Y-%m'),
            'rotulo': f'{MESES[mes.month - 1]}/{str(mes.year)[2:]}',
            'gerado_kwh': round(gerado.get(mes, 0.0), 3),
            'esperado_kwh': round(esperado_mes, 3),
            'esperado_ate_hoje_kwh': round(esperado_ate, 3),
            'parcial': i == 0,
        })
    return resultado


def dashboard(usinas, hoje: date | None = None) -> dict:
    hoje = hoje or timezone.localdate()
    lista = list(anotar_usinas(usinas, hoje))
    for u in lista:
        u.esperado_ate_hoje_kwh = esperado_ate_hoje(u, hoje)

    def soma(campo):
        return round(sum(float(getattr(u, campo) or 0) for u in lista), 3)

    gerado_mes, esperado_mes = soma('geracao_mes_kwh'), soma('esperado_mes_kwh')
    esperado_ate = soma('esperado_ate_hoje_kwh')
    por_status = {s: sum(1 for u in lista if u.status == s) for s in Status.values}

    # Motivo de atenção: alerta aberto mais recente de cada usina
    alertas = {}
    for a in Alerta.objects.filter(usina__in=[u.pk for u in lista], fim__isnull=True).order_by('inicio'):
        alertas[a.usina_id] = a.mensagem or a.get_tipo_display()

    # Noite (sem sol) é normal: não entra em "precisam de atenção"
    atencao = sorted((u for u in lista if u.status not in (Status.ONLINE, Status.NOITE)),
                     key=lambda u: (u.status != Status.OFFLINE, u.nome))
    desempenho = sorted(
        ((u, u.geracao_mes_kwh / u.esperado_ate_hoje_kwh * 100) for u in lista if u.esperado_ate_hoje_kwh),
        key=lambda par: par[1],
    )[:5]

    return {
        'kpis': {
            'geracao_hoje_kwh': soma('geracao_hoje_kwh'),
            'potencia_atual_kw': soma('potencia_atual_kw'),
            'geracao_mes_kwh': gerado_mes,
            'esperado_mes_kwh': esperado_mes,
            'esperado_ate_hoje_kwh': esperado_ate,
            # Gerado no mês × esperado ATÉ HOJE (não o mês inteiro)
            'desempenho_mes_pct': round(gerado_mes / esperado_ate * 100, 1) if esperado_ate else None,
            'potencia_instalada_kwp': round(sum(float(u.potencia_kwp) for u in lista), 2),
            'total': len(lista),
            **por_status,
        },
        'atencao': [{
            'id': u.id, 'nome': u.nome, 'status': u.status,
            'ultima_leitura': u.ultima_leitura,
            'motivo': alertas.get(u.id) or ('Sem comunicação' if u.status == Status.OFFLINE else 'Verificar usina'),
        } for u in atencao],
        'menor_desempenho': [{'id': u.id, 'nome': u.nome, 'pct': round(p, 1)} for u, p in desempenho],
        'curva_hoje': curva_da_carteira(usinas, hoje),
        'geracao_mensal': geracao_mensal(usinas, 12, hoje),
    }
