from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from integracoes.cadastro import CadastroErro, cadastrar_por_sn

from .models import Usuario
from .permissoes import COLABORADOR, EhEquipe, perfil_de
from .serializers import (
    EuSerializer, LoginSerializer, TrocarSenhaSerializer, UsuarioSerializer, VincularInversorSerializer,
)


class LoginView(TokenObtainPairView):
    """POST e-mail + senha → tokens de acesso (access) e de renovação (refresh)."""
    serializer_class = LoginSerializer


class EuView(RetrieveUpdateAPIView):
    """GET dados do usuário logado · PATCH nome e WhatsApp."""
    serializer_class = EuSerializer
    http_method_names = ['get', 'patch', 'options']

    def get_object(self):
        return self.request.user


class TrocarSenhaView(APIView):
    def post(self, request):
        serializer = TrocarSenhaSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['senha_nova'])
        request.user.save(update_fields=['password'])
        return Response({'detail': 'Senha alterada.'})


class UsuarioViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Usuários (Admin e Colaborador). Não há exclusão: desative com {"ativo": false}.
    Colaborador só vê e cadastra usuários com perfil Cliente.
    """
    serializer_class = UsuarioSerializer
    permission_classes = [EhEquipe]
    http_method_names = ['get', 'post', 'patch', 'options']
    search_fields = ['nome', 'email', 'cpf', 'whatsapp']
    ordering_fields = ['nome', 'email', 'perfil', 'criado_em', 'last_login']
    ordering = ['nome']

    def _e_colaborador(self) -> bool:
        return perfil_de(self.request.user) == COLABORADOR

    def get_queryset(self):
        qs = Usuario.objects.prefetch_related('usinas')
        if self._e_colaborador():
            qs = qs.filter(perfil=Usuario.Perfil.CLIENTE)
        if perfil := self.request.query_params.get('perfil'):
            qs = qs.filter(perfil=perfil)
        if (ativo := self.request.query_params.get('ativo')) in ('true', 'false'):
            qs = qs.filter(is_active=ativo == 'true')
        return qs

    def perform_create(self, serializer):
        if self._e_colaborador():
            serializer.save(perfil=Usuario.Perfil.CLIENTE)
        else:
            serializer.save()

    def perform_update(self, serializer):
        if self._e_colaborador():
            serializer.validated_data.pop('perfil', None)   # colaborador não muda perfil
        serializer.save()

    @action(detail=True, methods=['post'], url_path='vincular-inversor')
    def vincular_inversor(self, request, pk=None):
        """Cadastra a usina do inversor (SN) na plataforma escolhida e vincula ao cliente."""
        cliente = self.get_object()
        dados = VincularInversorSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        try:
            r = cadastrar_por_sn(dados.validated_data['plataforma'], dados.validated_data['sn'], cliente)
        except (CadastroErro, ValueError) as erro:
            return Response({'detail': str(erro)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'detail': f'Usina "{r.usina.nome}" ' + (
                'cadastrada e vinculada.' if r.usina_nova
                else 'reativada (com o histórico anterior) e vinculada.' if r.reativada
                else 'vinculada.'),
            'usina': {'id': r.usina.id, 'nome': r.usina.nome},
            'usina_nova': r.usina_nova,
            'reativada': r.reativada,
            'inversores': r.inversores,
        }, status=status.HTTP_201_CREATED if r.usina_nova else status.HTTP_200_OK)
