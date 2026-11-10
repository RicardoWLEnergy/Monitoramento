"""Conversão de usuários de/para JSON, com as mesmas validações do modelo."""
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from usinas.models import Plataforma

from .models import Usuario, normalizar_cpf, normalizar_whatsapp


def _validar_com(funcao, valor):
    """Usa as funções de normalização do modelo e devolve o erro no formato da API."""
    try:
        return funcao(valor)
    except DjangoValidationError as erro:
        raise serializers.ValidationError(erro.messages)


class LoginSerializer(TokenObtainPairSerializer):
    """Login por e-mail + senha. O e-mail é comparado em minúsculas."""

    default_error_messages = {'no_active_account': 'E-mail ou senha incorretos.'}

    def validate(self, attrs):
        attrs[self.username_field] = (attrs.get(self.username_field) or '').strip().lower()
        return super().validate(attrs)


class UsuarioSerializer(serializers.ModelSerializer):
    # Campos sem o validador automático de unicidade: normalizamos antes e conferimos à mão
    email = serializers.EmailField()
    cpf = serializers.CharField(max_length=14, required=False, allow_blank=True, allow_null=True)
    whatsapp = serializers.CharField(max_length=20, required=False, allow_blank=True, allow_null=True)

    senha = serializers.CharField(write_only=True, required=False, style={'input_type': 'password'})
    ativo = serializers.BooleanField(source='is_active', required=False)
    cpf_formatado = serializers.CharField(read_only=True)
    link_maps = serializers.CharField(read_only=True)
    usinas = serializers.SerializerMethodField()

    class Meta:
        model = Usuario
        fields = [
            'id', 'email', 'nome', 'whatsapp', 'cpf', 'cpf_formatado',
            'endereco', 'latitude', 'longitude', 'link_maps',
            'perfil', 'ativo', 'criado_em', 'last_login', 'senha', 'usinas',
        ]
        read_only_fields = ['criado_em', 'last_login']

    def get_usinas(self, obj):
        return [{'id': u.id, 'nome': u.nome} for u in obj.usinas.all()]

    def _ja_existe(self, **filtro) -> bool:
        qs = Usuario.objects.filter(**filtro)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        return qs.exists()

    def validate_email(self, valor):
        valor = valor.strip().lower()
        if self._ja_existe(email=valor):
            raise serializers.ValidationError('Já existe um usuário com este e-mail.')
        return valor

    def validate_cpf(self, valor):
        cpf = _validar_com(normalizar_cpf, valor)
        if cpf and self._ja_existe(cpf=cpf):
            raise serializers.ValidationError('Já existe um usuário com este CPF.')
        return cpf

    def validate_whatsapp(self, valor):
        numero = _validar_com(normalizar_whatsapp, valor)
        if numero and self._ja_existe(whatsapp=numero):
            raise serializers.ValidationError('Já existe um usuário com este WhatsApp.')
        return numero

    def validate_senha(self, valor):
        _validar_com(lambda s: validate_password(s, self.instance), valor)
        return valor

    def create(self, dados):
        senha = dados.pop('senha', None)
        usuario = Usuario(**dados)
        if senha:
            usuario.set_password(senha)
        else:
            usuario.set_unusable_password()   # entra depois por "definir senha" / token WhatsApp
        usuario.save()
        return usuario

    def update(self, usuario, dados):
        senha = dados.pop('senha', None)
        usuario = super().update(usuario, dados)
        if senha:
            usuario.set_password(senha)
            usuario.save(update_fields=['password'])
        return usuario


class EuSerializer(UsuarioSerializer):
    """O próprio usuário: pode alterar só nome e WhatsApp."""

    class Meta(UsuarioSerializer.Meta):
        fields = ['id', 'email', 'nome', 'whatsapp', 'cpf_formatado', 'endereco', 'link_maps', 'perfil', 'last_login']
        read_only_fields = ['email', 'endereco', 'perfil', 'last_login']


class TrocarSenhaSerializer(serializers.Serializer):
    senha_atual = serializers.CharField(style={'input_type': 'password'})
    senha_nova = serializers.CharField(style={'input_type': 'password'})

    def validate_senha_atual(self, valor):
        if not self.context['request'].user.check_password(valor):
            raise serializers.ValidationError('Senha atual incorreta.')
        return valor

    def validate_senha_nova(self, valor):
        _validar_com(lambda s: validate_password(s, self.context['request'].user), valor)
        return valor


class VincularInversorSerializer(serializers.Serializer):
    plataforma = serializers.ChoiceField(choices=Plataforma.choices)
    sn = serializers.CharField(max_length=60)
