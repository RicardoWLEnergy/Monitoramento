import re
from urllib.parse import quote_plus

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


def normalizar_whatsapp(valor: str | None) -> str | None:
    """
    Converte o número para o formato internacional usado pelas APIs de WhatsApp.
    Ex.: "(61) 99999-8888" -> "+5561999998888". Sem código do país, assume Brasil (+55).
    Vazio vira None (assim o campo único aceita vários usuários sem número).
    """
    if not valor or not valor.strip():
        return None
    digitos = re.sub(r'\D', '', valor)
    if not valor.strip().startswith('+') and len(digitos) in (10, 11):
        digitos = '55' + digitos
    if not 12 <= len(digitos) <= 15:
        raise ValidationError('Número de WhatsApp inválido. Use DDD + número, ex.: (61) 99999-8888.')
    return '+' + digitos


def normalizar_cpf(valor: str | None) -> str | None:
    """
    Guarda só os 11 dígitos e confere os dígitos verificadores.
    Ex.: "123.456.789-09" -> "12345678909". Vazio vira None.
    """
    if not valor or not valor.strip():
        return None
    cpf = re.sub(r'\D', '', valor)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        raise ValidationError('CPF inválido.')
    for posicao in (9, 10):
        soma = sum(int(cpf[i]) * (posicao + 1 - i) for i in range(posicao))
        digito = (soma * 10 % 11) % 10
        if digito != int(cpf[posicao]):
            raise ValidationError('CPF inválido.')
    return cpf


def link_google_maps(endereco: str = '', latitude=None, longitude=None) -> str | None:
    """Link que abre o Google Maps: pelas coordenadas, se houver; senão pelo endereço."""
    if latitude is not None and longitude is not None:
        return f'https://www.google.com/maps/search/?api=1&query={latitude},{longitude}'
    if endereco:
        return f'https://www.google.com/maps/search/?api=1&query={quote_plus(endereco)}'
    return None


class UsuarioManager(BaseUserManager):
    """Cria usuários usando o e-mail como login (no lugar de username)."""

    use_in_migrations = True

    def create_user(self, email, password=None, **campos):
        if not email:
            raise ValueError('O e-mail é obrigatório.')
        usuario = self.model(email=self.normalize_email(email), **campos)
        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, email, password=None, **campos):
        campos.setdefault('perfil', Usuario.Perfil.ADMIN)
        campos.setdefault('is_superuser', True)
        return self.create_user(email, password, **campos)


class Usuario(AbstractBaseUser, PermissionsMixin):
    """Pessoa que acessa o sistema. O perfil define o que ela pode fazer."""

    class Perfil(models.TextChoices):
        ADMIN = 'admin', 'Admin'                    # gerencia tudo
        COLABORADOR = 'colaborador', 'Colaborador'  # cadastra clientes e vincula usinas
        CLIENTE = 'cliente', 'Cliente'              # só visualiza as próprias usinas

    email = models.EmailField('e-mail', unique=True)
    nome = models.CharField('nome', max_length=150)
    whatsapp = models.CharField(
        'WhatsApp', max_length=16, unique=True, null=True, blank=True,
        help_text='Formato internacional, ex.: +5561999998888',
    )
    perfil = models.CharField('perfil', max_length=20, choices=Perfil.choices, default=Perfil.CLIENTE)

    # --- Dados do cliente ---
    cpf = models.CharField('CPF', max_length=11, unique=True, null=True, blank=True,
                           help_text='Só números; os dígitos verificadores são conferidos.')
    endereco = models.CharField('endereço', max_length=255, blank=True)
    latitude = models.DecimalField('latitude', max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField('longitude', max_digits=9, decimal_places=6, null=True, blank=True)

    is_active = models.BooleanField(
        'ativo', default=True,
        help_text='Desmarque para bloquear o acesso sem apagar o usuário.',
    )
    criado_em = models.DateTimeField('criado em', default=timezone.now)

    objects = UsuarioManager()

    USERNAME_FIELD = 'email'        # campo usado no login
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = ['nome']      # pedido também no createsuperuser

    class Meta:
        verbose_name = 'usuário'
        verbose_name_plural = 'usuários'
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} <{self.email}>'

    @property
    def is_staff(self) -> bool:
        """Acesso ao painel /admin do Django: só o perfil Admin."""
        return self.perfil == self.Perfil.ADMIN

    @property
    def cpf_formatado(self) -> str:
        c = self.cpf or ''
        return f'{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}' if len(c) == 11 else ''

    @property
    def link_maps(self) -> str | None:
        return link_google_maps(self.endereco, self.latitude, self.longitude)

    def clean(self):
        super().clean()
        self.whatsapp = normalizar_whatsapp(self.whatsapp)
        self.cpf = normalizar_cpf(self.cpf)

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()  # "Ana@X.com" e "ana@x.com" são a mesma conta
        self.whatsapp = normalizar_whatsapp(self.whatsapp)
        self.cpf = normalizar_cpf(self.cpf)
        super().save(*args, **kwargs)
