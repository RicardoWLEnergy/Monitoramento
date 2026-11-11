from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from usuarios.permissoes import EhEquipe, usinas_visiveis

from .consultas import dashboard
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
        if params.get('usina'):
            qs = qs.filter(usina_id=params['usina'])
        if params.get('tipo'):
            qs = qs.filter(tipo=params['tipo'])
        return qs
