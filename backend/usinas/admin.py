from django.contrib import admin
from django.utils.html import format_html

from .models import GeracaoEsperada, Inversor, Usina


class InversorInline(admin.TabularInline):
    model = Inversor
    extra = 0
    fields = ('numero_serie', 'id_externo', 'modelo', 'potencia_nominal_kw', 'status', 'potencia_atual_kw', 'ultima_leitura')
    readonly_fields = ('status', 'potencia_atual_kw', 'ultima_leitura')


class GeracaoEsperadaInline(admin.TabularInline):
    model = GeracaoEsperada
    extra = 0
    max_num = 12


@admin.register(Usina)
class UsinaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'plataforma', 'fabricante', 'cidade', 'potencia_kwp', 'status', 'ultima_leitura', 'ativa')
    list_filter = ('ativa', 'plataforma', 'fabricante', 'status', 'alertas_ativos')
    actions = ['reativar']
    search_fields = ('nome', 'id_externo', 'cidade', 'usuarios__nome', 'usuarios__email')
    filter_horizontal = ('usuarios',)
    readonly_fields = ('status', 'ultima_leitura', 'criado_em', 'atualizado_em', 'desativada_em', 'mapa')
    inlines = [InversorInline, GeracaoEsperadaInline]
    fieldsets = (
        ('Origem', {'fields': ('plataforma', 'id_externo', 'fabricante')}),
        ('Dados da usina', {'fields': ('nome', 'potencia_kwp', 'fuso_horario')}),
        ('Localização', {'fields': ('endereco', 'cidade', 'uf', 'latitude', 'longitude', 'mapa')}),
        ('Situação', {'fields': ('status', 'ultima_leitura')}),
        ('Clientes vinculados', {'fields': ('usuarios',)}),
        ('Alertas', {'fields': ('alertas_ativos', 'limite_desempenho_pct', 'minutos_sem_comunicacao')}),
        ('Registro', {'fields': ('ativa', 'desativada_em', 'criado_em', 'atualizado_em')}),
    )

    @admin.action(description='Reativar usinas selecionadas')
    def reativar(self, request, queryset):
        total = queryset.filter(ativa=False).update(ativa=True, desativada_em=None)
        self.message_user(request, f'{total} usina(s) reativada(s). Vincule os clientes novamente.')

    @admin.display(description='mapa')
    def mapa(self, obj):
        link = obj.link_maps
        return format_html('<a href="{}" target="_blank" rel="noopener">Abrir no Google Maps →</a>', link) if link else '—'


@admin.register(Inversor)
class InversorAdmin(admin.ModelAdmin):
    list_display = ('numero_serie', 'modelo', 'usina', 'status', 'potencia_atual_kw', 'geracao_hoje_kwh', 'ultima_leitura')
    list_filter = ('status', 'usina__fabricante')
    search_fields = ('numero_serie', 'id_externo', 'modelo', 'usina__nome')
    list_select_related = ('usina',)
