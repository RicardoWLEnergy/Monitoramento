from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.utils.html import format_html

from .models import Usuario, normalizar_cpf, normalizar_whatsapp


class CamposClienteMixin(forms.Form):
    """Aceita CPF e WhatsApp digitados com pontuação e converte antes de validar."""

    cpf = forms.CharField(label='CPF', max_length=14, required=False, help_text='Ex.: 529.982.247-25')
    whatsapp = forms.CharField(label='WhatsApp', max_length=20, required=False, help_text='Ex.: (61) 99999-8888')

    def clean_cpf(self):
        return normalizar_cpf(self.cleaned_data.get('cpf'))

    def clean_whatsapp(self):
        return normalizar_whatsapp(self.cleaned_data.get('whatsapp'))


class UsuarioCriacaoForm(CamposClienteMixin, UserCreationForm):
    """Formulário de 'adicionar usuário' apontando para o NOSSO modelo (login por e-mail)."""

    class Meta:
        model = Usuario
        fields = ('email', 'nome', 'whatsapp', 'cpf', 'endereco', 'perfil')


class UsuarioAlteracaoForm(CamposClienteMixin, UserChangeForm):
    class Meta:
        model = Usuario
        fields = '__all__'


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    """Tela de usuários no /admin, adaptada para login por e-mail."""

    add_form = UsuarioCriacaoForm
    form = UsuarioAlteracaoForm

    list_display = ('nome', 'email', 'perfil', 'whatsapp', 'cpf_formatado', 'is_active', 'last_login')
    list_filter = ('perfil', 'is_active')
    search_fields = ('nome', 'email', 'whatsapp', 'cpf')
    ordering = ('nome',)

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Dados pessoais', {'fields': ('nome', 'whatsapp', 'cpf')}),
        ('Endereço', {'fields': ('endereco', 'latitude', 'longitude', 'mapa')}),
        ('Acesso', {'fields': ('perfil', 'is_active', 'is_superuser')}),
        ('Datas', {'fields': ('last_login', 'criado_em')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nome', 'whatsapp', 'cpf', 'endereco', 'perfil', 'password1', 'password2'),
        }),
    )
    readonly_fields = ('last_login', 'criado_em', 'mapa')
    filter_horizontal = ()

    @admin.display(description='CPF')
    def cpf_formatado(self, obj):
        return obj.cpf_formatado

    @admin.display(description='mapa')
    def mapa(self, obj):
        link = obj.link_maps
        return format_html('<a href="{}" target="_blank" rel="noopener">Abrir no Google Maps →</a>', link) if link else '—'
