"""
Consultas de geração usadas pela API (lista de usinas, detalhe e dashboard).
Recebem sempre um conjunto de usinas JÁ filtrado pelo perfil do usuário.
"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import DateTimeField, F, FloatField, Func, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Cast, Coalesce, TruncMonth
from django.utils import timezone

from usinas.models import GeracaoEsperada, Inversor, Status

from .models import Alerta, GeracaoDiaria, Leitura

MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez']


def _primeiro_dia(d: date, meses_atras: int = 0) -> date:
    total = d.year * 12 + d.month - 1 - meses_atras
    return date(total // 12, total % 12 + 1, 1)


def _soma(qs, campo: str):
    """Subconsulta: soma de `campo` por usina (evita duplicar linhas ao juntar várias tabelas)."""
    sub = qs.filter(usina=OuterRef('pk')).values('usina').annotate(t=Sum(campo)).values('t')
    return Coalesce(Cast(Subquery(sub), FloatField()), Value(0.0))


def anotar_usinas(usinas, hoje: date | None = None):
    """Acrescenta a cada usina: potência atual, geração de hoje, do mês e o esperado do mês."""
    hoje = hoje or timezone.localdate()
    return usinas.annotate(
        potencia_atual_kw=_soma(Inversor.objects.all(), 'potencia_atual_kw'),
        geracao_hoje_kwh=_soma(Inversor.objects.all(), 'geracao_hoje_kwh'),
        geracao_mes_kwh=_soma(GeracaoDiaria.objects.filter(data__gte=_primeiro_dia(hoje), data__lte=hoje), 'energia_kwh'),
        esperado_mes_kwh=_soma(GeracaoEsperada.objects.filter(mes=hoje.month), 'energia_kwh'),
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
    """Últimos `meses` meses: gerado (soma dos dias) × esperado. O mês atual vem marcado como parcial."""
    hoje = hoje or timezone.localdate()
    inicio = _primeiro_dia(hoje, meses - 1)

    gerado = {
        l['mes'].date() if hasattr(l['mes'], 'date') else l['mes']: float(l['total'] or 0)
        for l in GeracaoDiaria.objects.filter(usina__in=usinas, data__gte=inicio, data__lte=hoje)
        .annotate(mes=TruncMonth('data')).values('mes').annotate(total=Sum('energia_kwh'))
    }
    esperado = {
        l['mes']: float(l['total'] or 0)
        for l in GeracaoEsperada.objects.filter(usina__in=usinas).values('mes').annotate(total=Sum('energia_kwh'))
    }

    resultado = []
    for i in range(meses - 1, -1, -1):
        mes = _primeiro_dia(hoje, i)
        resultado.append({
            'mes': mes.strftime('%Y-%m'),
            'rotulo': f'{MESES[mes.month - 1]}/{str(mes.year)[2:]}',
            'gerado_kwh': round(gerado.get(mes, 0.0), 3),
            'esperado_kwh': round(esperado.get(mes.month, 0.0), 3),
            'parcial': i == 0,
        })
    return resultado


def dashboard(usinas, hoje: date | None = None) -> dict:
    hoje = hoje or timezone.localdate()
    lista = list(anotar_usinas(usinas, hoje))

    def soma(campo):
        return round(sum(float(getattr(u, campo) or 0) for u in lista), 3)

    gerado_mes, esperado_mes = soma('geracao_mes_kwh'), soma('esperado_mes_kwh')
    por_status = {s: sum(1 for u in lista if u.status == s) for s in Status.values}

    # Motivo de atenção: alerta aberto mais recente de cada usina
    alertas = {}
    for a in Alerta.objects.filter(usina__in=[u.pk for u in lista], fim__isnull=True).order_by('inicio'):
        alertas[a.usina_id] = a.mensagem or a.get_tipo_display()

    atencao = sorted((u for u in lista if u.status != Status.ONLINE),
                     key=lambda u: (u.status != Status.OFFLINE, u.nome))
    desempenho = sorted(
        ((u, u.geracao_mes_kwh / u.esperado_mes_kwh * 100) for u in lista if u.esperado_mes_kwh),
        key=lambda par: par[1],
    )[:5]

    return {
        'kpis': {
            'geracao_hoje_kwh': soma('geracao_hoje_kwh'),
            'potencia_atual_kw': soma('potencia_atual_kw'),
            'geracao_mes_kwh': gerado_mes,
            'esperado_mes_kwh': esperado_mes,
            'desempenho_mes_pct': round(gerado_mes / esperado_mes * 100, 1) if esperado_mes else None,
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
