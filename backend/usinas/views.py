from datetime import date

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from integracoes.coleta import cobertura, importar_periodo
from integracoes.foxess import FoxESSErro
from integracoes.huawei import HuaweiErro
from monitoramento.consultas import anotar_usinas, curva_do_dia, geracao_mensal
from usuarios.models import Usuario
from usuarios.permissoes import EhAdmin, EhEquipe, usinas_visiveis

from .models import GeracaoEsperada, Status
from .serializers import (
    GeracaoEsperadaSerializer, ImportarHistoricoSerializer, InversorSerializer, UsinaAlertasSerializer,
    UsinaDetalheSerializer, UsinaListaSerializer, VinculoClientesSerializer,
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
            return UsinaAlertasSerializer
        return UsinaDetalheSerializer

    def get_permissions(self):
        if self.action in ('partial_update', 'destroy'):
            return [EhAdmin()]                       # alertas e "apagar": só Admin
        if self.action in ('clientes', 'historico'):
            return [EhEquipe()]                      # vincular clientes / importar histórico: Admin e Colaborador
        if self.action == 'geracao_esperada' and self.request.method == 'PUT':
            return [EhAdmin()]
        return super().get_permissions()

    def update(self, request, *args, **kwargs):
        if not kwargs.get('partial'):
            return Response({'detail': 'Use PATCH.'}, status=405)
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
    @action(detail=True)
    def inversores(self, request, pk=None):
        return Response(InversorSerializer(self.get_object().inversores.all(), many=True).data)

    @action(detail=True)
    def curva(self, request, pk=None):
        """?data=AAAA-MM-DD (padrão: hoje)."""
        try:
            dia = date.fromisoformat(request.query_params.get('data') or timezone.localdate().isoformat())
        except ValueError:
            raise serializers.ValidationError({'data': 'Use o formato AAAA-MM-DD.'})
        usina = self.get_object()
        return Response({'data': dia.isoformat(), 'fuso': usina.fuso_horario, 'pontos': curva_do_dia(usina, dia)})

    @action(detail=True, url_path='geracao-mensal')
    def geracao_mensal(self, request, pk=None):
        """?meses=12 (1 a 36)."""
        meses = min(max(int(request.query_params.get('meses') or 12), 1), 36)
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
        GET  o que já existe no banco (dias de energia e de curva).
        POST {"inicio": "2026-10-01", "fim": "2026-11-09", "curvas": true} importa da plataforma.
        Leva ~1 s por inversor por dia de curva (limite da FoxESS) — a resposta só volta no fim.
        """
        usina = self.get_object()
        if request.method == 'POST':
            dados = ImportarHistoricoSerializer(data=request.data)
            dados.is_valid(raise_exception=True)
            try:
                resultado = importar_periodo(usina, **dados.validated_data)
            except (FoxESSErro, HuaweiErro, ValueError) as erro:
                return Response({'detail': str(erro)}, status=400)
            return Response({**resultado, 'cobertura': cobertura(usina)})
        return Response(cobertura(usina))
