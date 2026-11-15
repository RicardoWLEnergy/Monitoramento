from django.contrib import admin

from .models import Alerta, GeracaoDiaria, ImportacaoHistorico

# Leitura não aparece aqui: o Django não permite /admin para tabelas com chave
# primária composta (e são milhões de linhas). Consulte pelo Beekeeper ou pela API.

@admin.register(GeracaoDiaria)
class GeracaoDiariaAdmin(admin.ModelAdmin):
    list_display = ('usina', 'data', 'energia_kwh')
    list_filter = ('usina__fabricante', 'usina')
    date_hierarchy = 'data'
    list_select_related = ('usina',)


@admin.register(Alerta)
class AlertaAdmin(admin.ModelAdmin):
    list_display = ('usina', 'tipo', 'inversor', 'inicio', 'fim', 'aberto')
    list_filter = ('tipo', ('fim', admin.EmptyFieldListFilter), 'usina__fabricante')
    search_fields = ('usina__nome', 'mensagem')
    date_hierarchy = 'inicio'
    list_select_related = ('usina', 'inversor')

    @admin.display(boolean=True, description='aberto')
    def aberto(self, obj):
        return obj.aberto


@admin.register(ImportacaoHistorico)
class ImportacaoHistoricoAdmin(admin.ModelAdmin):
    list_display = ('usina', 'inicio', 'fim', 'curvas', 'status', 'passos_feitos', 'passos_total', 'criado_em')
    list_filter = ('status',)
    search_fields = ('usina__nome',)
    list_select_related = ('usina',)
