from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from usuarios.models import link_google_maps


class Plataforma(models.TextChoices):
    """De onde vêm os dados da usina (nuvem de monitoramento)."""
    FOXESS = 'foxess', 'FoxESS Cloud'
    HUAWEI = 'huawei', 'Huawei FusionSolar'


class Fabricante(models.TextChoices):
    """Marca dos inversores (o que aparece para o usuário)."""
    WEG = 'weg', 'WEG'
    FOXESS = 'foxess', 'FoxESS'
    HUAWEI = 'huawei', 'Huawei'


class Status(models.TextChoices):
    ONLINE = 'online', 'Online'
    ALERTA = 'alerta', 'Alerta'
    OFFLINE = 'offline', 'Offline'


class UsinaQuerySet(models.QuerySet):
    def ativas(self):
        return self.filter(ativa=True)


class Usina(models.Model):
    """
    Usina fotovoltaica. Entra no banco quando um cliente é cadastrado com a SN de
    um inversor dela: os dados vêm da plataforma (FoxESS/Huawei) e o cliente é vinculado.

    "Apagar" uma usina só a DESATIVA: ela some do sistema, mas o histórico fica no banco.
    Cadastrar de novo uma SN dela a reativa (ver integracoes/cadastro.py).
    """

    # --- Origem dos dados ---
    plataforma = models.CharField('plataforma', max_length=10, choices=Plataforma.choices)
    id_externo = models.CharField(
        'ID na plataforma', max_length=100,
        help_text='Identificador da usina na plataforma (FoxESS: stationID; Huawei: plantCode).',
    )
    fabricante = models.CharField(
        'fabricante dos inversores', max_length=10, choices=Fabricante.choices,
        help_text='Detectado pelo modelo dos inversores (ex.: SIW… = WEG).',
    )

    # --- Dados cadastrais (vêm da plataforma) ---
    nome = models.CharField('nome', max_length=150)
    endereco = models.CharField('endereço', max_length=255, blank=True)
    cidade = models.CharField('cidade', max_length=100, blank=True)
    uf = models.CharField('UF', max_length=2, blank=True)
    latitude = models.DecimalField('latitude', max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField('longitude', max_digits=9, decimal_places=6, null=True, blank=True)
    fuso_horario = models.CharField('fuso horário', max_length=50, default='America/Sao_Paulo')
    potencia_kwp = models.DecimalField('potência instalada (kWp)', max_digits=10, decimal_places=2, default=0)

    # --- Situação atual (atualizada a cada coleta) ---
    status = models.CharField('status', max_length=10, choices=Status.choices, default=Status.OFFLINE)
    ultima_leitura = models.DateTimeField('última leitura', null=True, blank=True)

    # --- Clientes vinculados (Admin e Colaborador gerenciam) ---
    usuarios = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='usinas', blank=True,
        limit_choices_to={'perfil': 'cliente'}, verbose_name='clientes vinculados',
    )

    # --- Configurações de alerta (só o Admin altera) ---
    alertas_ativos = models.BooleanField('alertas ativos', default=True)
    limite_desempenho_pct = models.PositiveSmallIntegerField(
        'alertar abaixo de (% do esperado)', default=85,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
    )
    minutos_sem_comunicacao = models.PositiveSmallIntegerField(
        'considerar offline após (min)', default=60, validators=[MinValueValidator(5)],
    )

    # --- Desativação ("apagar") ---
    ativa = models.BooleanField('ativa', default=True, help_text='Desativada = some do sistema, mas o histórico fica.')
    desativada_em = models.DateTimeField('desativada em', null=True, blank=True)

    criado_em = models.DateTimeField('criado em', auto_now_add=True)
    atualizado_em = models.DateTimeField('atualizado em', auto_now=True)

    objects = UsinaQuerySet.as_manager()

    class Meta:
        verbose_name = 'usina'
        verbose_name_plural = 'usinas'
        ordering = ['nome']
        constraints = [
            # A mesma usina da mesma plataforma não pode entrar duas vezes
            models.UniqueConstraint(fields=['plataforma', 'id_externo'], name='usina_unica_por_plataforma'),
        ]

    def __str__(self):
        return f'{self.nome} ({self.get_fabricante_display()})'

    @property
    def link_maps(self) -> str | None:
        endereco = ', '.join(p for p in (self.endereco, self.cidade, self.uf) if p)
        return link_google_maps(endereco, self.latitude, self.longitude)

    def desativar(self) -> None:
        """'Apaga' a usina: some do sistema e perde os vínculos de clientes; o histórico fica."""
        self.ativa = False
        self.desativada_em = timezone.now()
        self.save(update_fields=['ativa', 'desativada_em', 'atualizado_em'])
        self.usuarios.clear()


class Inversor(models.Model):
    """Inversor de uma usina. A situação atual é atualizada a cada coleta."""

    usina = models.ForeignKey(Usina, on_delete=models.CASCADE, related_name='inversores', verbose_name='usina')
    numero_serie = models.CharField('número de série (SN)', max_length=60, unique=True)
    id_externo = models.CharField(
        'ID na plataforma', max_length=100, blank=True,
        help_text='Huawei usa um ID próprio do equipamento; na FoxESS é a própria SN.',
    )
    tipo_externo = models.CharField(
        'tipo na plataforma', max_length=10, blank=True,
        help_text='Huawei: devTypeId (1 = inversor string, 38 = residencial). Vazio na FoxESS.',
    )
    modelo = models.CharField('modelo', max_length=100, blank=True)
    potencia_nominal_kw = models.DecimalField('potência nominal (kW)', max_digits=8, decimal_places=2, default=0)

    status = models.CharField('status', max_length=10, choices=Status.choices, default=Status.OFFLINE)
    potencia_atual_kw = models.DecimalField('potência atual (kW)', max_digits=10, decimal_places=3, default=0)
    geracao_hoje_kwh = models.DecimalField('geração hoje (kWh)', max_digits=12, decimal_places=3, default=0)
    ultima_leitura = models.DateTimeField('última leitura', null=True, blank=True)

    class Meta:
        verbose_name = 'inversor'
        verbose_name_plural = 'inversores'
        ordering = ['usina', 'numero_serie']

    def __str__(self):
        return f'{self.modelo or "Inversor"} · {self.numero_serie}'


class GeracaoEsperada(models.Model):
    """Energia esperada para cada mês do ano (12 linhas por usina) — base do 'gerado × esperado'."""

    usina = models.ForeignKey(Usina, on_delete=models.CASCADE, related_name='geracao_esperada', verbose_name='usina')
    mes = models.PositiveSmallIntegerField('mês', validators=[MinValueValidator(1), MaxValueValidator(12)])
    energia_kwh = models.DecimalField('energia esperada (kWh)', max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = 'geração esperada'
        verbose_name_plural = 'geração esperada'
        ordering = ['usina', 'mes']
        constraints = [
            models.UniqueConstraint(fields=['usina', 'mes'], name='esperado_unico_por_mes'),
            models.CheckConstraint(condition=models.Q(mes__gte=1, mes__lte=12), name='esperado_mes_valido'),
        ]

    def __str__(self):
        return f'{self.usina} · mês {self.mes}: {self.energia_kwh} kWh'
