import logging
from datetime import timedelta

import requests
from django.contrib.auth.models import update_last_login
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import AuthenticationFailed, Throttled, ValidationError
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from integracoes.cadastro import CadastroErro, cadastrar_por_sn
from integracoes.foxess import FoxESSErro
from integracoes.huawei import HuaweiErro
from integracoes.uazapi import UazapiErro, configurado, enviar_texto

from .models import CodigoAcesso, Usuario, mascarar_whatsapp
from .permissoes import COLABORADOR, EhEquipe, perfil_de
from .serializers import (
    EntrarComCodigoSerializer, EuSerializer, LoginSerializer, PedirCodigoSerializer, TrocarSenhaSerializer,
    UsuarioSerializer, VincularInversorSerializer,
)

log = logging.getLogger(__name__)


# ---------- Limite de tentativas ----------
class LimiteDeTentativas:
    """Até 10 tentativas por minuto por IP (DEFAULT_THROTTLE_RATES); mensagem em português."""
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def throttled(self, request, wait):
        segundos = int(wait or 60) + 1
        raise Throttled(wait, detail=f'Muitas tentativas. Tente de novo em {segundos} segundos.')


MAX_ERROS_SENHA = 10                 # erros de senha seguidos no mesmo e-mail...
BLOQUEIO_SENHA_SEGUNDOS = 15 * 60    # ...bloqueiam o login com senha desse e-mail por 15 min


class LoginView(LimiteDeTentativas, TokenObtainPairView):
    """POST e-mail + senha → tokens de acesso (access) e de renovação (refresh)."""
    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        email = str(request.data.get('email') or '').strip().lower()
        chave = f'login-erros:{email}'
        if (cache.get(chave) or 0) >= MAX_ERROS_SENHA:
            return Response({'detail': 'Muitas tentativas com senha errada. Tente de novo em 15 minutos '
                                       'ou entre com o código pelo WhatsApp.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        try:
            resposta = super().post(request, *args, **kwargs)
        except AuthenticationFailed:
            cache.add(chave, 0, BLOQUEIO_SENHA_SEGUNDOS)
            try:
                cache.incr(chave)
            except ValueError:            # expirou entre o add e o incr
                cache.set(chave, 1, BLOQUEIO_SENHA_SEGUNDOS)
            raise
        cache.delete(chave)
        return resposta


class RenovarView(LimiteDeTentativas, TokenRefreshView):
    """POST refresh → novo access."""
    throttle_scope = 'renovar'


# ---------- Login com código pelo WhatsApp ----------
# Mensagem do WhatsApp (*texto* = negrito no WhatsApp). Emojis só aqui, a pedido do responsável:
# na interface e nos documentos da marca continuam proibidos.
MENSAGEM_CODIGO = (
    '🔐 *WL Energy · Monitoramento* 🔐\n'
    '\n'
    'Código de acesso: *{codigo}*\n'
    '\n'
    '⏱️ Válido por 5 minutos.\n'
    '🚫 Não compartilhe com ninguém.\n'
    '\n'
    'Se você não pediu este código, avise a WL Energy.'
)
SEM_WHATSAPP = ('Não foi possível enviar um código para este e-mail. '
                'Entre com a senha ou fale com a W.L Energy para cadastrar seu WhatsApp.')
ENVIO_INDISPONIVEL = 'Não foi possível enviar o código agora. Tente de novo em alguns minutos ou entre com a senha.'
CODIGO_INVALIDO = 'Código inválido ou expirado. Peça um novo código.'


class PedirCodigoView(LimiteDeTentativas, APIView):
    """POST {"email"} → envia um código de 6 números para o WhatsApp cadastrado nesse e-mail."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        dados = PedirCodigoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        usuario = (Usuario.objects.filter(email=dados.validated_data['email'], is_active=True)
                   .exclude(whatsapp__isnull=True).first())
        if usuario is None:
            return Response({'detail': SEM_WHATSAPP}, status=status.HTTP_400_BAD_REQUEST)

        if not configurado():
            log.warning('Login por código: uazapi não configurada (UAZAPI_URL/UAZAPI_TOKEN).')
            return Response({'detail': ENVIO_INDISPONIVEL}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Trava o usuário: pedidos simultâneos esperam um pelo outro (não furam os limites)
        with transaction.atomic():
            Usuario.objects.select_for_update().filter(pk=usuario.pk).first()
            agora = timezone.now()
            ultimo_dia = usuario.codigos_acesso.filter(criado_em__gte=agora - timedelta(days=1))
            ultimo = ultimo_dia.first()
            if ultimo and agora - ultimo.criado_em < CodigoAcesso.INTERVALO_REENVIO:
                espera = int((CodigoAcesso.INTERVALO_REENVIO - (agora - ultimo.criado_em)).total_seconds()) + 1
                return Response({'detail': f'Aguarde {espera} segundos para pedir outro código.',
                                 'espera_segundos': espera}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            if ultimo_dia.filter(criado_em__gte=agora - timedelta(hours=1)).count() >= CodigoAcesso.MAX_POR_HORA:
                return Response({'detail': 'Muitos códigos pedidos na última hora. Tente mais tarde ou entre com a senha.'},
                                status=status.HTTP_429_TOO_MANY_REQUESTS)
            if ultimo_dia.count() >= CodigoAcesso.MAX_POR_DIA:
                log.warning('Login por código: limite diário atingido para o usuário %s.', usuario.pk)
                return Response({'detail': 'Limite de códigos de hoje atingido. Entre com a senha ou tente amanhã.'},
                                status=status.HTTP_429_TOO_MANY_REQUESTS)
            registro, codigo = CodigoAcesso.gerar(usuario)

        try:
            enviar_texto(usuario.whatsapp, MENSAGEM_CODIGO.format(codigo=codigo))
        except UazapiErro as erro:
            registro.delete()              # não enviou: não conta no limite e não vale para entrar
            log.warning('Login por código: envio falhou para o usuário %s: %s', usuario.pk, erro)
            return Response({'detail': ENVIO_INDISPONIVEL}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        numero = mascarar_whatsapp(usuario.whatsapp)
        return Response({'detail': f'Código enviado para o número {numero}.', 'numero': numero,
                         'validade_minutos': int(CodigoAcesso.VALIDADE.total_seconds() // 60),
                         'reenvio_segundos': int(CodigoAcesso.INTERVALO_REENVIO.total_seconds())})


class EntrarComCodigoView(LimiteDeTentativas, APIView):
    """POST {"email", "codigo"} → tokens de acesso, iguais aos do login com senha."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        dados = EntrarComCodigoSerializer(data=request.data)
        dados.is_valid(raise_exception=True)
        usuario = Usuario.objects.filter(email=dados.validated_data['email'], is_active=True).first()
        if usuario is None:
            return Response({'detail': CODIGO_INVALIDO}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            # Só o código mais recente vale; a trava evita duas tentativas ao mesmo tempo
            registro = usuario.codigos_acesso.select_for_update().first()
            if registro is None or not registro.valido:
                return Response({'detail': CODIGO_INVALIDO}, status=status.HTTP_400_BAD_REQUEST)
            if not registro.confere(dados.validated_data['codigo']):
                registro.tentativas += 1
                registro.save(update_fields=['tentativas'])
                restantes = CodigoAcesso.MAX_TENTATIVAS - registro.tentativas
                texto = (f'Código incorreto. {restantes} tentativa(s) restante(s).' if restantes
                         else 'Código incorreto. Ele foi bloqueado: peça um novo código.')
                return Response({'detail': texto}, status=status.HTTP_400_BAD_REQUEST)
            registro.usado_em = timezone.now()
            registro.save(update_fields=['usado_em'])

        update_last_login(None, usuario)
        refresh = RefreshToken.for_user(usuario)
        return Response({'access': str(refresh.access_token), 'refresh': str(refresh)})


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
        # Os logins abertos caem com a troca (CHECK_REVOKE_TOKEN); este recebe tokens novos
        refresh = RefreshToken.for_user(request.user)
        return Response({'detail': 'Senha alterada.', 'access': str(refresh.access_token), 'refresh': str(refresh)})


class UsuarioViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin,
                     mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """
    Usuários (Admin e Colaborador). Não há exclusão: desative com {"ativo": false}.
    Colaborador só vê e cadastra usuários com perfil Cliente.
    """
    serializer_class = UsuarioSerializer
    permission_classes = [EhEquipe]
    http_method_names = ['get', 'post', 'patch', 'options']
    search_fields = ['nome', 'email', 'cpf', 'whatsapp', 'id_cliente']
    ordering_fields = ['nome', 'email', 'perfil', 'criado_em', 'last_login']
    ordering = ['nome']

    def _e_colaborador(self) -> bool:
        return perfil_de(self.request.user) == COLABORADOR

    def get_queryset(self):
        qs = Usuario.objects.prefetch_related('usinas')
        if self._e_colaborador():
            qs = qs.filter(perfil=Usuario.Perfil.CLIENTE)
        if perfil := self.request.query_params.get('perfil'):
            qs = qs.filter(perfil__in=perfil.split(','))   # ex.: ?perfil=admin,colaborador
        if (ativo := self.request.query_params.get('ativo')) in ('true', 'false'):
            qs = qs.filter(is_active=ativo == 'true')
        return qs

    def perform_create(self, serializer):
        if self._e_colaborador():
            serializer.save(perfil=Usuario.Perfil.CLIENTE)
        else:
            serializer.save()

    def perform_update(self, serializer):
        dados = serializer.validated_data
        if self._e_colaborador():
            dados.pop('perfil', None)   # colaborador não muda perfil
        if serializer.instance == self.request.user:
            # Evita ficar sem acesso por engano (ex.: o último Admin se rebaixar ou se desativar)
            if 'perfil' in dados and dados['perfil'] != self.request.user.perfil:
                raise ValidationError({'perfil': 'Você não pode mudar o seu próprio perfil.'})
            if dados.get('is_active') is False:
                raise ValidationError({'ativo': 'Você não pode desativar o seu próprio acesso.'})
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
        except (requests.RequestException, FoxESSErro, HuaweiErro) as erro:
            log.warning('Cadastro por SN: plataforma indisponível: %s', erro)
            return Response({'detail': 'Não foi possível consultar a plataforma agora. Tente de novo em alguns minutos.'},
                            status=status.HTTP_502_BAD_GATEWAY)
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
