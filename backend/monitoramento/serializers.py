from rest_framework import serializers

from .models import Alerta, ImportacaoHistorico


class AlertaSerializer(serializers.ModelSerializer):
    usina_nome = serializers.CharField(source='usina.nome', read_only=True)
    inversor_sn = serializers.CharField(source='inversor.numero_serie', read_only=True, default=None)
    tipo_nome = serializers.CharField(source='get_tipo_display', read_only=True)
    aberto = serializers.BooleanField(read_only=True)

    class Meta:
        model = Alerta
        fields = ['id', 'usina', 'usina_nome', 'inversor_sn', 'tipo', 'tipo_nome', 'mensagem', 'inicio', 'fim', 'aberto']


class ImportacaoHistoricoSerializer(serializers.ModelSerializer):
    """Situação de uma importação de histórico (mostrada em Configurações da usina)."""
    status_nome = serializers.CharField(source='get_status_display', read_only=True)
    etapa_nome = serializers.CharField(source='get_etapa_display', read_only=True)
    solicitado_por_nome = serializers.CharField(source='solicitado_por.nome', read_only=True, default=None)

    class Meta:
        model = ImportacaoHistorico
        fields = ['id', 'inicio', 'fim', 'curvas', 'status', 'status_nome', 'etapa', 'etapa_nome',
                  'passos_feitos', 'passos_total', 'dias_energia', 'dias_curva', 'leituras', 'falhas',
                  'solicitado_por_nome', 'criado_em', 'iniciado_em', 'concluido_em']
