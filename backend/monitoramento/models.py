from django.conf import settings
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


class ImportacaoHistorico(models.Model):
    """
    Pedido de importação de histórico (botão em Configurações da usina).

    A tela só registra o pedido; quem executa é o coletor (`manage.py coletar`), em pedaços
    (1 mês de energia ou 1 dia de curva por vez) no tempo livre entre os ciclos de tempo real.
    O progresso fica salvo a cada pedaço: se o coletor reiniciar, continua de onde parou.
    """

    class Status(models.TextChoices):
        FILA = 'fila', 'Na fila'
        IMPORTANDO = 'importando', 'Importando'
        CONCLUIDA = 'concluida', 'Concluída'
        ERRO = 'erro', 'Erro'

    class Etapa(models.TextChoices):
        ENERGIA = 'energia', 'Energia diária'
        CURVA = 'curva', 'Curva de 5 min'

    ATIVOS = (Status.FILA, Status.IMPORTANDO)
    MAX_FALHAS = 20
    MAX_ERROS_TEMPORARIOS = 5

    usina = models.ForeignKey(Usina, on_delete=models.CASCADE, related_name='importacoes', verbose_name='usina')
    inicio = models.DateField('de')
    fim = models.DateField('até')
    curvas = models.BooleanField('com curva de 5 min', default=True)
    solicitado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+', verbose_name='solicitado por')
    criado_em = models.DateTimeField('solicitado em', auto_now_add=True)
    iniciado_em = models.DateTimeField('iniciado em', null=True, blank=True)
    concluido_em = models.DateTimeField('concluído em', null=True, blank=True)

    status = models.CharField('status', max_length=12, choices=Status.choices, default=Status.FILA)
    etapa = models.CharField('etapa', max_length=10, choices=Etapa.choices, default=Etapa.ENERGIA)
    cursor = models.DateField('próximo dia', null=True, blank=True,
                              help_text='Dia mais recente ainda não importado na etapa atual (vai do fim ao início).')
    passos_feitos = models.PositiveIntegerField('passos feitos', default=0)
    passos_total = models.PositiveIntegerField('passos no total', default=0)

    dias_energia = models.PositiveIntegerField('dias de energia', default=0)
    dias_curva = models.PositiveIntegerField('dias de curva', default=0)
    leituras = models.PositiveIntegerField('leituras', default=0)
    falhas = models.JSONField('falhas', default=list, blank=True)
    # Erro passageiro (sem conexão, login recusado): pausa e tenta de novo; após MAX_ERROS_TEMPORARIOS, desiste
    erros_temporarios = models.PositiveSmallIntegerField('erros passageiros seguidos', default=0)
    tentar_apos = models.DateTimeField('tentar de novo após', null=True, blank=True)

    class Meta:
        verbose_name = 'importação de histórico'
        verbose_name_plural = 'importações de histórico'
        ordering = ['-criado_em']
        constraints = [
            # No máximo uma importação na fila/em andamento por usina
            models.UniqueConstraint(fields=['usina'], condition=models.Q(status__in=['fila', 'importando']),
                                    name='uma_importacao_ativa_por_usina'),
        ]

    def __str__(self):
        return f'{self.usina} · {self.inicio:%d/%m/%Y}–{self.fim:%d/%m/%Y} · {self.get_status_display()}'

    @property
    def ativa(self) -> bool:
        return self.status in self.ATIVOS

    def anotar_falhas(self, falhas: list[str]) -> None:
        """Guarda até MAX_FALHAS mensagens, sem repetir."""
        for f in falhas:
            if f not in self.falhas and len(self.falhas) < self.MAX_FALHAS:
                self.falhas.append(f)


class ClimaDiario(models.Model):
    """Clima do dia na usina (Open-Meteo): ensolarado, nublado ou chuvoso, e a chuva em mm."""

    class Condicao(models.TextChoices):
        ENSOLARADO = 'ensolarado', 'Ensolarado'
        NUBLADO = 'nublado', 'Nublado'
        CHUVOSO = 'chuvoso', 'Chuvoso'

    usina = models.ForeignKey(Usina, on_delete=models.CASCADE, related_name='clima', verbose_name='usina')
    data = models.DateField('data')
    condicao = models.CharField('condição', max_length=10, choices=Condicao.choices)
    chuva_mm = models.FloatField('chuva (mm)', default=0)
    codigo = models.PositiveSmallIntegerField('código WMO', null=True, blank=True)
    atualizado_em = models.DateTimeField('atualizado em', auto_now=True)

    class Meta:
        verbose_name = 'clima do dia'
        verbose_name_plural = 'clima por dia'
        ordering = ['usina', '-data']
        constraints = [models.UniqueConstraint(fields=['usina', 'data'], name='clima_unico_por_dia')]

    def __str__(self):
        return f'{self.usina} · {self.data:%d/%m/%Y} · {self.get_condicao_display()}'
