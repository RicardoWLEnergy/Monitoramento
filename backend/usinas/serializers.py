from django.utils import timezone
from rest_framework import serializers

from usuarios.permissoes import e_equipe

from .models import GeracaoEsperada, Inversor, Usina


class UsinaListaSerializer(serializers.ModelSerializer):
    plataforma_nome = serializers.CharField(source='get_plataforma_display', read_only=True)
    fabricante_nome = serializers.CharField(source='get_fabricante_display', read_only=True)
    # Calculados na consulta (monitoramento.consultas.anotar_usinas)
    potencia_atual_kw = serializers.FloatField(read_only=True)
    geracao_hoje_kwh = serializers.FloatField(read_only=True)
    geracao_mes_kwh = serializers.FloatField(read_only=True)
    esperado_mes_kwh = serializers.FloatField(read_only=True)

    class Meta:
        model = Usina
        fields = [
            'id', 'nome', 'plataforma', 'plataforma_nome', 'fabricante', 'fabricante_nome',
            'cidade', 'uf', 'potencia_kwp', 'status', 'ultima_leitura',
            'potencia_atual_kw', 'geracao_hoje_kwh', 'geracao_mes_kwh', 'esperado_mes_kwh',
        ]


class UsinaDetalheSerializer(UsinaListaSerializer):
    link_maps = serializers.CharField(read_only=True)
    clientes = serializers.SerializerMethodField()

    class Meta(UsinaListaSerializer.Meta):
        fields = UsinaListaSerializer.Meta.fields + [
            'id_externo', 'endereco', 'latitude', 'longitude', 'link_maps', 'fuso_horario',
            'alertas_ativos', 'limite_desempenho_pct', 'minutos_sem_comunicacao', 'clientes',
        ]

    def get_clientes(self, obj):
        return [{'id': u.id, 'nome': u.nome, 'email': u.email} for u in obj.usuarios.all()]

    def to_representation(self, obj):
        dados = super().to_representation(obj)
        if not e_equipe(self.context['request'].user):
            dados.pop('clientes')   # cliente não vê quem mais está vinculado
        return dados


class UsinaAlertasSerializer(serializers.ModelSerializer):
    """O que o Admin pode alterar numa usina (o resto vem da plataforma)."""

    class Meta:
        model = Usina
        fields = ['alertas_ativos', 'limite_desempenho_pct', 'minutos_sem_comunicacao']


class InversorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inversor
        fields = ['id', 'numero_serie', 'modelo', 'potencia_nominal_kw', 'status',
                  'potencia_atual_kw', 'geracao_hoje_kwh', 'ultima_leitura']


class GeracaoEsperadaSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeracaoEsperada
        fields = ['mes', 'energia_kwh']


class VinculoClientesSerializer(serializers.Serializer):
    clientes = serializers.ListField(child=serializers.IntegerField(), allow_empty=True)


class ImportarHistoricoSerializer(serializers.Serializer):
    """Período a importar da plataforma (botão "Importar histórico")."""

    MAX_DIAS = 400

    inicio = serializers.DateField()
    fim = serializers.DateField()
    curvas = serializers.BooleanField(default=True, help_text='Importar também a curva de 5 min (mais lento).')

    def validate(self, dados):
        hoje = timezone.localdate()
        if dados['fim'] > hoje:
            raise serializers.ValidationError({'fim': 'A data final não pode ser no futuro.'})
        if dados['inicio'] > dados['fim']:
            raise serializers.ValidationError({'inicio': 'A data inicial precisa ser antes da final.'})
        if (dados['fim'] - dados['inicio']).days + 1 > self.MAX_DIAS:
            raise serializers.ValidationError({'inicio': f'Período máximo de {self.MAX_DIAS} dias por importação.'})
        return dados
