import logging
from urllib.parse import quote

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from integracoes import google, obras
from usuarios.permissoes import EhEquipe, perfil_de, usinas_visiveis

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


# ----------------------------------------------------------------------------
# Meu projeto (planilha OBRAS + documentos do Drive)
# ----------------------------------------------------------------------------
log = logging.getLogger(__name__)
PLANILHA_INDISPONIVEL = 'Não foi possível carregar o seu projeto agora. Tente de novo em alguns minutos.'


def _id_cliente_da_requisicao(request) -> str | None:
    """O cliente vê SÓ o próprio projeto (pelo ID do cadastro). A equipe pode ver o de um cliente: ?id_cliente=."""
    if perfil_de(request.user) == 'cliente':
        return request.user.id_cliente
    return (request.query_params.get('id_cliente') or '').strip() or None


class ProjetoView(APIView):
    """GET o projeto de instalação do cliente logado (ou {"projeto": null} se não houver)."""

    def get(self, request):
        id_cliente = _id_cliente_da_requisicao(request)
        try:
            linha = obras.linha_do_cliente(id_cliente)
        except obras.PlanilhaIndisponivel as erro:
            log.warning('Meu projeto: planilha indisponível: %s', erro)
            return Response({'detail': PLANILHA_INDISPONIVEL}, status=503)
        return Response({'projeto': obras.montar_projeto(linha, id_cliente) if linha else None})


class DocumentoProjetoView(APIView):
    """GET o arquivo (PDF) de um documento do projeto. Só da linha do próprio cliente."""

    def get(self, request, tipo):
        if tipo not in obras.DOCUMENTOS:
            return Response({'detail': 'Documento inexistente.'}, status=404)
        id_cliente = _id_cliente_da_requisicao(request)
        try:
            linha = obras.linha_do_cliente(id_cliente)
        except obras.PlanilhaIndisponivel as erro:
            log.warning('Documento do projeto: planilha indisponível: %s', erro)
            return Response({'detail': PLANILHA_INDISPONIVEL}, status=503)
        arquivo_id = obras.id_do_arquivo(linha, tipo) if linha else None
        if not arquivo_id:
            return Response({'detail': 'Este documento ainda não está disponível.'}, status=404)
        try:
            arquivo = google.baixar_arquivo(arquivo_id)
        except google.GoogleErro as erro:
            log.warning('Documento do projeto %s (%s): %s', tipo, id_cliente, erro)
            return Response({'detail': 'Não foi possível baixar o documento agora. Tente de novo em alguns minutos.'},
                            status=502)
        resposta = HttpResponse(arquivo.conteudo, content_type=arquivo.tipo)
        resposta['Content-Disposition'] = f"attachment; filename*=UTF-8''{quote(arquivo.nome)}"
        return resposta
