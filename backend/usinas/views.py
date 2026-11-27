from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from integracoes.clima import clima_por_dia
from integracoes.coleta import cobertura
from monitoramento.consultas import anotar_usinas, curva_do_dia, geracao_mensal, geracao_por_dia, ler_data, ler_periodo
from monitoramento.models import ImportacaoHistorico
from monitoramento.serializers import ImportacaoHistoricoSerializer
from usuarios.models import Usuario
from usuarios.permissoes import ADMIN, EhAdmin, EhEquipe, perfil_de, usinas_visiveis

from .models import GeracaoEsperada, Plataforma, Status, Usina
from .serializers import (
    CAMPOS_ALERTAS, GeracaoEsperadaSerializer, ImportarHistoricoSerializer, InversorSerializer,
    PotenciaNominalSerializer, UsinaDetalheSerializer, UsinaEdicaoSerializer, UsinaListaSerializer, VinculoClientesSerializer,
)


class UsinaViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                   mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    Usinas visíveis ao usuário (todas para a equipe; só as vinculadas para o cliente).
    Filtros: ?busca= ?status= ?fabricante= ?plataforma= ?ordem= ?page=
    """
    http_method_names = ['get', 'post', 'patch', 'put', 'delete', 'options']   # POST só em ações (ex.: historico)
    search_fields = ['nome', 'cidade', 'id_externo', 'usuarios__nome', 'inversores__numero_serie']
    ordering_fields = ['nome', 'fabricante', 'potencia_kwp', 'status', 'ultima_leitura',
                       'potencia_atual_kw', 'geracao_hoje_kwh', 'geracao_mes_kwh']
    ordering = ['nome']

    def get_queryset(self):
        qs = usinas_visiveis(self.request.user).prefetch_related('usuarios')
        for campo in ('status', 'fabricante', 'plataforma'):
            if valor := self.request.query_params.get(campo):
                qs = qs.filter(**{campo: valor})
        return anotar_usinas(qs)

    def get_serializer_class(self):
        if self.action == 'list':
            return UsinaListaSerializer
        if self.action == 'partial_update':
            return UsinaEdicaoSerializer
        return UsinaDetalheSerializer

    def get_permissions(self):
        if self.action == 'destroy':
            return [EhAdmin()]                       # "apagar": só Admin
        if self.action in ('partial_update', 'clientes', 'historico'):
            return [EhEquipe()]                      # editar, vincular clientes, importar histórico: Admin e Colaborador
        if self.action in ('geracao_esperada', 'inversores') and self.request.method == 'PUT':
            return [EhEquipe()]                      # prognóstico e potência dos inversores: Admin e Colaborador
        return super().get_permissions()

    def update(self, request, *args, **kwargs):
        if not kwargs.get('partial'):
            return Response({'detail': 'Use PATCH.'}, status=405)
        if perfil_de(request.user) != ADMIN and any(campo in request.data for campo in CAMPOS_ALERTAS):
            return Response({'detail': 'Apenas administradores alteram os alertas.'}, status=403)
        super().update(request, *args, **kwargs)
        return Response(UsinaDetalheSerializer(self.get_object(), context=self.get_serializer_context()).data)

    def perform_destroy(self, usina):
        """'Apagar' = desativar: some do sistema, perde os vínculos, mas o histórico fica no banco."""
        usina.desativar()

    # ---------- resumo (chips da lista) ----------
    @action(detail=False)
    def resumo(self, request):
        qs = usinas_visiveis(request.user)
        return Response({
            'total': qs.count(),
            'potencia_kwp': float(qs.aggregate(t=Sum('potencia_kwp'))['t'] or 0),
            **{s: qs.filter(status=s).count() for s in Status.values},
        })

    # ---------- dados de uma usina ----------
    @action(detail=True, methods=['get', 'put'])
    def inversores(self, request, pk=None):
        """GET a lista · PUT [{"id": 5, "potencia_nominal_kw": 10}, ...] corrige a potência nominal (equipe)."""
        usina = self.get_object()
        if request.method == 'PUT':
            dados = PotenciaNominalSerializer(data=request.data, many=True)
            dados.is_valid(raise_exception=True)
            por_id = {i.id: i for i in usina.inversores.all()}
            if any(item['id'] not in por_id for item in dados.validated_data):
                return Response({'detail': 'Inversor não pertence a esta usina.'}, status=400)
            with transaction.atomic():
                for item in dados.validated_data:
                    inv = por_id[item['id']]
                    inv.potencia_nominal_kw = item['potencia_nominal_kw']
                    inv.save(update_fields=['potencia_nominal_kw'])
        return Response(InversorSerializer(usina.inversores.all(), many=True).data)

    @action(detail=True)
    def curva(self, request, pk=None):
        """?data=AAAA-MM-DD (padrão: hoje)."""
        try:
            dia = ler_data(request.query_params.get('data'), timezone.localdate())
        except ValueError as erro:
            raise serializers.ValidationError({'data': str(erro)})
        usina = self.get_object()
        return Response({'data': dia.isoformat(), 'fuso': usina.fuso_horario, 'pontos': curva_do_dia(usina, dia),
                         'clima': clima_por_dia(usina, dia, dia).get(dia)})

    @action(detail=True, url_path='geracao-diaria')
    def geracao_diaria(self, request, pk=None):
        """?inicio=AAAA-MM-DD&fim=AAAA-MM-DD (padrão: últimos 30 dias; até 366 dias)."""
        try:
            inicio, fim = ler_periodo(request.query_params)
        except ValueError as erro:
            raise serializers.ValidationError({'detail': str(erro)})
        usina = self.get_object()
        dias = geracao_por_dia(Usina.objects.filter(pk=usina.pk), inicio, fim)
        climas = clima_por_dia(usina, inicio, fim)
        for d in dias:
            d['clima'] = climas.get(date.fromisoformat(d['data']))
        return Response({'inicio': inicio.isoformat(), 'fim': fim.isoformat(), 'dias': dias})

    @action(detail=True, url_path='geracao-mensal')
    def geracao_mensal(self, request, pk=None):
        """?meses=12 (1 a 36)."""
        try:
            meses = min(max(int(request.query_params.get('meses') or 12), 1), 36)
        except ValueError:
            meses = 12
        usina = self.get_object()
        return Response(geracao_mensal(usinas_visiveis(request.user).filter(pk=usina.pk), meses))

    @action(detail=True, methods=['get', 'put'], url_path='geracao-esperada')
    def geracao_esperada(self, request, pk=None):
        """GET os 12 valores · PUT [{"mes": 1, "energia_kwh": 1200}, ...] (Admin)."""
        usina = self.get_object()
        if request.method == 'PUT':
            dados = GeracaoEsperadaSerializer(data=request.data, many=True)
            dados.is_valid(raise_exception=True)
            with transaction.atomic():
                for item in dados.validated_data:
                    GeracaoEsperada.objects.update_or_create(
                        usina=usina, mes=item['mes'], defaults={'energia_kwh': item['energia_kwh']})
        return Response(GeracaoEsperadaSerializer(usina.geracao_esperada.all(), many=True).data)

    @action(detail=True, methods=['put'])
    def clientes(self, request, pk=None):
        """PUT {"clientes": [ids]} — define a lista de clientes vinculados."""
        usina = self.get_object()
        dados = VinculoClientesSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        ids = set(dados.validated_data['clientes'])
        clientes = list(Usuario.objects.filter(pk__in=ids, perfil=Usuario.Perfil.CLIENTE))
        if len(clientes) != len(ids):
            raise serializers.ValidationError({'clientes': 'Só usuários com perfil Cliente podem ser vinculados.'})
        usina.usuarios.set(clientes)
        return Response(UsinaDetalheSerializer(self.get_object(), context=self.get_serializer_context()).data)

    @action(detail=True, methods=['get', 'post'])
    def historico(self, request, pk=None):
        """
        GET  o que já existe no banco (dias de energia e de curva) + a importação mais recente.
        POST {"inicio": "2026-10-01", "fim": "2026-11-09", "curvas": true} coloca a importação na fila.
        Quem importa é o coletor, no tempo livre entre os ciclos de tempo real: a resposta volta na hora
        e a tela acompanha o progresso pelo GET.
        """
        usina = self.get_object()
        if request.method == 'POST':
            dados = ImportarHistoricoSerializer(data=request.data)
            dados.is_valid(raise_exception=True)
            if usina.plataforma not in (Plataforma.FOXESS, Plataforma.HUAWEI, Plataforma.SUNGROW):
                return Response({'detail': 'Esta plataforma não tem importação de histórico.'}, status=400)
            if usina.importacoes.filter(status__in=ImportacaoHistorico.ATIVOS).exists():
                return Response({'detail': 'Já existe uma importação em andamento para esta usina.'}, status=409)
            periodo = dict(dados.validated_data)
            if usina.inicio_operacao:   # antes do início da operação tudo seria zero: nem pede à plataforma
                if periodo['fim'] < usina.inicio_operacao:
                    return Response({'detail': f'A usina começou a operar em {usina.inicio_operacao:%d/%m/%Y}: '
                                               'escolha um período a partir dessa data.'}, status=400)
                periodo['inicio'] = max(periodo['inicio'], usina.inicio_operacao)
            try:
                with transaction.atomic():
                    ImportacaoHistorico.objects.create(usina=usina, solicitado_por=request.user, **periodo)
            except IntegrityError:   # dois cliques ao mesmo tempo
                return Response({'detail': 'Já existe uma importação em andamento para esta usina.'}, status=409)
            return Response(self._situacao_historico(usina), status=202)
        return Response(self._situacao_historico(usina))

    @staticmethod
    def _situacao_historico(usina) -> dict:
        ultima = usina.importacoes.select_related('solicitado_por').first()
        return {**cobertura(usina), 'importacao': ImportacaoHistoricoSerializer(ultima).data if ultima else None}
