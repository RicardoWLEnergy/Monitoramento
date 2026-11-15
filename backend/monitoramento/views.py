from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from usuarios.permissoes import EhEquipe, usinas_visiveis

from .consultas import curva_da_carteira, dashboard, geracao_por_dia, ler_data, ler_periodo
from .models import Alerta
from .serializers import AlertaSerializer


class DashboardView(APIView):
    """
    Visão geral da carteira (KPIs, curva de hoje, usinas que precisam de atenção, ranking, histórico).
    Só para a equipe WL (Admin e Colaborador): o Cliente vê direto a(s) usina(s) dele.
    """
    permission_classes = [EhEquipe]

    def get(self, request):
        return Response(dashboard(usinas_visiveis(request.user)))


class DashboardCurvaView(APIView):
    """Potência somada das usinas num dia: ?data=AAAA-MM-DD (padrão: hoje). Só a equipe."""
    permission_classes = [EhEquipe]

    def get(self, request):
        try:
            dia = ler_data(request.query_params.get('data'), timezone.localdate())
        except ValueError as erro:
            raise serializers.ValidationError({'detail': str(erro)})
        return Response({'data': dia.isoformat(), 'pontos': curva_da_carteira(usinas_visiveis(request.user), dia)})


class DashboardGeracaoDiariaView(APIView):
    """Energia de cada dia, somando as usinas: ?inicio=&fim= (padrão: últimos 30 dias; até 1 ano). Só a equipe."""
    permission_classes = [EhEquipe]

    def get(self, request):
        try:
            inicio, fim = ler_periodo(request.query_params)
        except ValueError as erro:
            raise serializers.ValidationError({'detail': str(erro)})
        dias = geracao_por_dia(usinas_visiveis(request.user), inicio, fim)
        return Response({'inicio': inicio.isoformat(), 'fim': fim.isoformat(), 'dias': dias})


class AlertaViewSet(viewsets.ReadOnlyModelViewSet):
    """Alertas das usinas visíveis. Filtros: ?aberto=true|false ?usina=<id> ?tipo=<tipo>"""
    serializer_class = AlertaSerializer
    search_fields = ['usina__nome', 'mensagem']
    ordering_fields = ['inicio', 'fim', 'tipo']
    ordering = ['-inicio']

    def get_queryset(self):
        qs = Alerta.objects.filter(usina__in=usinas_visiveis(self.request.user)).select_related('usina', 'inversor')
        params = self.request.query_params
        if params.get('aberto') in ('true', 'false'):
            qs = qs.filter(fim__isnull=params['aberto'] == 'true')
        if params.get('usina', '').isdigit():
            qs = qs.filter(usina_id=params['usina'])
        if params.get('tipo'):
            qs = qs.filter(tipo=params['tipo'])
        return qs
