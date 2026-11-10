from django.db import models
from django.utils import timezone

from usinas.models import Inversor, Usina


class Leitura(models.Model):
    """
    Potência da usina num instante (a cada ~5 min). Forma a curva do dia.

    Tabela de alto volume (~288 linhas/usina/dia), por isso:
    - chave primária composta (usina, data_hora): sem coluna "id" e sem duplicar horário;
    - particionada por mês no PostgreSQL (ver particoes.py e a migração 0002);
    - mantida por LEITURAS_RETENCAO_MESES (os totais diários ficam para sempre em GeracaoDiaria).
    Obs.: o Django não permite exibir tabelas com chave composta no /admin.
    """

    pk = models.CompositePrimaryKey('usina_id', 'data_hora')
    usina = models.ForeignKey(Usina, on_delete=models.CASCADE, related_name='leituras', verbose_name='usina')
    data_hora = models.DateTimeField('data/hora')
    potencia_kw = models.FloatField('potência (kW)')

    class Meta:
        verbose_name = 'leitura'
        verbose_name_plural = 'leituras'
        ordering = ['usina', '-data_hora']

    def __str__(self):
        return f'{self.usina} · {self.data_hora:%d/%m/%Y %H:%M} · {self.potencia_kw} kW'


class GeracaoDiaria(models.Model):
    """Energia total gerada num dia. Base dos gráficos mensais e anuais."""

    usina = models.ForeignKey(Usina, on_delete=models.CASCADE, related_name='geracao_diaria', verbose_name='usina')
    data = models.DateField('data')
    energia_kwh = models.DecimalField('energia (kWh)', max_digits=12, decimal_places=3)

    class Meta:
        verbose_name = 'geração diária'
        verbose_name_plural = 'geração diária'
        ordering = ['usina', '-data']
        constraints = [
            models.UniqueConstraint(fields=['usina', 'data'], name='geracao_unica_por_dia'),
        ]

    def __str__(self):
        return f'{self.usina} · {self.data:%d/%m/%Y} · {self.energia_kwh} kWh'


class Alerta(models.Model):
    """Problema detectado numa usina. Fica aberto até 'fim' ser preenchido."""

    class Tipo(models.TextChoices):
        OFFLINE = 'offline', 'Sem comunicação'
        BAIXO_DESEMPENHO = 'baixo_desempenho', 'Geração abaixo do esperado'
        FALHA_INVERSOR = 'falha_inversor', 'Falha no inversor'

    usina = models.ForeignKey(Usina, on_delete=models.CASCADE, related_name='alertas', verbose_name='usina')
    inversor = models.ForeignKey(
        Inversor, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='alertas', verbose_name='inversor',
    )
    tipo = models.CharField('tipo', max_length=20, choices=Tipo.choices)
    mensagem = models.CharField('mensagem', max_length=255, blank=True)
    inicio = models.DateTimeField('início', default=timezone.now)
    fim = models.DateTimeField('fim', null=True, blank=True, help_text='Vazio = alerta ainda aberto.')

    class Meta:
        verbose_name = 'alerta'
        verbose_name_plural = 'alertas'
        ordering = ['-inicio']
        constraints = [
            # Não abre o mesmo alerta duas vezes enquanto o anterior não for encerrado
            models.UniqueConstraint(
                fields=['usina', 'tipo', 'inversor'], condition=models.Q(fim__isnull=True),
                nulls_distinct=False, name='alerta_aberto_unico',
            ),
            models.CheckConstraint(
                condition=models.Q(fim__isnull=True) | models.Q(fim__gte=models.F('inicio')),
                name='alerta_fim_depois_do_inicio',
            ),
        ]

    def __str__(self):
        return f'{self.usina} · {self.get_tipo_display()}'

    @property
    def aberto(self) -> bool:
        return self.fim is None
