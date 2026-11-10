from rest_framework import serializers

from .models import Alerta


class AlertaSerializer(serializers.ModelSerializer):
    usina_nome = serializers.CharField(source='usina.nome', read_only=True)
    inversor_sn = serializers.CharField(source='inversor.numero_serie', read_only=True, default=None)
    tipo_nome = serializers.CharField(source='get_tipo_display', read_only=True)
    aberto = serializers.BooleanField(read_only=True)

    class Meta:
        model = Alerta
        fields = ['id', 'usina', 'usina_nome', 'inversor_sn', 'tipo', 'tipo_nome', 'mensagem', 'inicio', 'fim', 'aberto']
