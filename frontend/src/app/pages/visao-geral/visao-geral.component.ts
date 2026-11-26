import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { DecimalPipe, I18nPluralPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import {
  ChevronLeft, ChevronRight,
  Activity, CalendarDays, Gauge, LucideAngularModule, TrendingUp, TriangleAlert, WifiOff, Zap,
} from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { Dashboard, DashboardService } from '../../services/dashboard.service';
import { GraficosService, echarts, numeroBR } from '../../services/graficos.service';
import {
  ATUALIZAR_A_CADA_MS, CardKpi, ESCALAS, Escala, agruparPorMes, cardsDoPeriodo, dataBR, deslocar, energiaBR, hojeIso,
  intervaloDa, pctBR, pctDoEsperado, picoDaCurva, resumoPeriodo,
} from '../../services/periodo';
import { DiaGeracao, GeracaoPeriodo, PontoCurva } from '../../services/usinas.service';

/** Visão geral: dashboard das usinas visíveis ao usuário — o que importa saber de relance. */
@Component({
  selector: 'app-visao-geral',
  imports: [DecimalPipe, I18nPluralPipe, RouterLink, NgxEchartsDirective, LucideAngularModule],
  providers: [provideEchartsCore({ echarts })],
  templateUrl: './visao-geral.component.html',
  styleUrl: './visao-geral.component.css',
})
export class VisaoGeralComponent {
  private readonly api = inject(DashboardService);
  private readonly graficos = inject(GraficosService);
  readonly auth = inject(AuthService);

  readonly icones = { ChevronLeft, ChevronRight, Activity, CalendarDays, Gauge, TriangleAlert, WifiOff, Zap };
  readonly hoje = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });

  readonly dados = signal<Dashboard | null>(null);
  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);

  readonly kpis = computed(() => this.dados()?.kpis);
  readonly temEsperado = computed(() => (this.dados()?.geracao_mensal ?? []).some(m => m.esperado_kwh > 0));
  // Gráfico de cima: "Dia" (potência somada) ou "Período" (energia de cada dia, somando as usinas)
  readonly modo = signal<'dia' | 'periodo'>('dia');
  readonly hojeIso = hojeIso();
  readonly dataCurva = signal(this.hojeIso);
  readonly curva = signal<PontoCurva[] | null>(null);   // null = a de hoje, que vem no painel
  /** Energia e esperado do dia escolhido no modo Dia (só quando não é hoje), somando as usinas. */
  readonly dadosDia = signal<DiaGeracao | null>(null);
  private ultimaAtualizacao = 0;
  // Período: semana / mês / ano com ‹ › (padrão: o mês atual) ou intervalo personalizado
  readonly escalas = ESCALAS;
  readonly escala = signal<Escala>('mes');
  readonly referencia = signal(hojeIso());
  readonly inicioPeriodo = signal(intervaloDa('mes', hojeIso()).inicio);   // usados no "Personalizado"
  readonly fimPeriodo = signal(hojeIso());
  readonly intervalo = computed(() => {
    const e = this.escala();
    return e === 'personalizado'
      ? { inicio: this.inicioPeriodo(), fim: this.fimPeriodo(), rotulo: '' }
      : intervaloDa(e, this.referencia());
  });
  /** Não avança além do período atual. */
  readonly podeAvancar = computed(() => this.intervalo().fim < this.hojeIso);
  readonly periodo = signal<GeracaoPeriodo | null>(null);
  readonly erroPeriodo = signal<string | null>(null);
  readonly resumoPeriodo = computed(() => resumoPeriodo(this.periodo()?.dias ?? []));
  /** Geração de hoje × esperado de hoje (somando as usinas). */
  readonly hojePct = computed(() => pctDoEsperado(this.kpis()?.geracao_hoje_kwh, this.kpis()?.esperado_hoje_kwh));

  /** Cards de outro dia ou do período escolhido no gráfico (null = cards de hoje). */
  readonly cardsVariaveis = computed<CardKpi[] | null>(() => {
    if (this.modo() === 'periodo') {
      return cardsDoPeriodo(this.resumoPeriodo(), !this.periodo() && !this.erroPeriodo(),
        { total: CalendarDays, media: Zap, esperado: Activity, melhor: TrendingUp });
    }
    if (this.dataCurva() === this.hojeIso) return null;
    const d = this.dadosDia();
    const pico = picoDaCurva(this.curva() ?? []);
    const k = this.kpis();
    return [
      { rotulo: 'Geração do dia', valor: d?.kwh != null ? energiaBR(d.kwh) : '—', detalhe: dataBR(this.dataCurva()), icone: CalendarDays },
      { rotulo: 'Pico do dia', valor: pico ? `${numeroBR(pico.kw, 1)} kW` : '—', detalhe: pico ? `às ${pico.hora}` : 'sem leituras', icone: TrendingUp },
      { rotulo: 'Gerado × esperado', valor: pctBR(pctDoEsperado(d?.kwh, d?.esperado_kwh)),
        detalhe: d?.esperado_kwh ? `esperado: ${energiaBR(d.esperado_kwh)}` : 'sem geração esperada cadastrada', icone: Activity },
      { rotulo: 'Potência instalada', valor: `${numeroBR(k?.potencia_instalada_kwp ?? 0, 2)} kWp`,
        detalhe: `${k?.total ?? 0} ${k?.total === 1 ? 'usina monitorada' : 'usinas monitoradas'}`, icone: Gauge },
    ];
  });

  readonly pontosCurva = computed(() => this.curva() ?? this.dados()?.curva_hoje ?? []);
  readonly opcoesCurva = computed(() => this.graficos.curvaPotencia(this.pontosCurva()));
  readonly opcoesPeriodo = computed(() => this.escala() === 'ano'
    ? this.graficos.geracaoMensal(
      agruparPorMes(this.periodo()?.dias ?? [], Number(this.intervalo().inicio.slice(0, 4)), this.hojeIso), 'MWh')
    : this.graficos.geracaoDiaria(this.periodo()?.dias ?? [], this.hojeIso));
  readonly opcoesMensal = computed(() => this.graficos.geracaoMensal(this.dados()?.geracao_mensal ?? [], 'MWh'));

  constructor() {
    this.carregar();
    // Atualiza sozinha a cada 5 min (o ritmo da coleta); confere a cada minuto, só com a aba visível
    const relogio = setInterval(() => this.atualizarSeVencido(), 60_000);
    inject(DestroyRef).onDestroy(() => clearInterval(relogio));
  }

  /** Atualização silenciosa: sem "Carregando..." e, se falhar, mantém o que está na tela. */
  private atualizarSeVencido(): void {
    if (document.hidden || !this.dados() || Date.now() - this.ultimaAtualizacao < ATUALIZAR_A_CADA_MS) return;
    this.ultimaAtualizacao = Date.now();
    this.api.carregar().subscribe({ next: d => this.dados.set(d), error: () => undefined });
    if (this.modo() === 'periodo' && this.fimAteHoje() === this.hojeIso) this.carregarPeriodo();
  }

  carregar(): void {
    this.ultimaAtualizacao = Date.now();
    this.carregando.set(true);
    this.erro.set(null);
    this.api.carregar().subscribe({
      next: d => { this.dados.set(d); this.carregando.set(false); },
      error: e => { this.erro.set(mensagemDeErro(e, 'Não foi possível carregar o painel.')); this.carregando.set(false); },
    });
  }

  mudarModo(modo: 'dia' | 'periodo'): void {
    this.modo.set(modo);
    if (modo === 'periodo' && !this.periodo()) this.carregarPeriodo();
  }

  mudarDia(data: string): void {
    if (!data) return;
    this.dataCurva.set(data);
    this.dadosDia.set(null);
    if (data === this.hojeIso) { this.curva.set(null); return; }
    this.api.curva(data).subscribe({ next: c => this.curva.set(c.pontos), error: () => this.curva.set([]) });
    this.api.geracaoDiaria(data, data).subscribe({
      next: p => this.dadosDia.set(p.dias[0] ?? null),
      error: () => this.dadosDia.set(null),
    });
  }

  mudarPeriodo(inicio: string, fim: string): void {
    if (!inicio || !fim) return;
    this.inicioPeriodo.set(inicio);
    this.fimPeriodo.set(fim);
    this.carregarPeriodo();
  }

  /** Semana / Mês / Ano / Personalizado. */
  mudarEscala(escala: Escala): void {
    if (escala === 'personalizado') {           // começa com o período que estava na tela
      this.inicioPeriodo.set(this.intervalo().inicio);
      this.fimPeriodo.set(this.fimAteHoje());
    }
    this.escala.set(escala);
    this.carregarPeriodo();
  }

  /** ‹ volta e › avança uma semana, um mês ou um ano. */
  navegar(passo: number): void {
    const e = this.escala();
    if (e === 'personalizado' || (passo > 0 && !this.podeAvancar())) return;
    this.referencia.set(deslocar(e, this.referencia(), passo));
    this.carregarPeriodo();
  }

  /** Fim do período sem passar de hoje (não há dados do futuro). */
  private fimAteHoje(): string {
    return this.intervalo().fim < this.hojeIso ? this.intervalo().fim : this.hojeIso;
  }

  carregarPeriodo(): void {
    this.erroPeriodo.set(null);
    this.api.geracaoDiaria(this.intervalo().inicio, this.fimAteHoje()).subscribe({
      next: p => this.periodo.set(p),
      error: e => {
        this.periodo.set(null);
        this.erroPeriodo.set(mensagemDeErro(e, 'Não foi possível carregar o período.'));
      },
    });
  }

  /** Clique numa barra: no Ano abre o mês; nos demais, a curva de potência do dia. */
  abrirDia(indice: number | undefined): void {
    if (indice === undefined) return;
    if (this.escala() === 'ano') {
      this.referencia.set(`${this.intervalo().inicio.slice(0, 4)}-${String(indice + 1).padStart(2, '0')}-01`);
      this.escala.set('mes');
      this.carregarPeriodo();
      return;
    }
    const dia = this.periodo()?.dias[indice];
    if (!dia) return;
    this.modo.set('dia');
    this.mudarDia(dia.data);
  }

  ultimaLeitura(iso: string | null): string {
    if (!iso) return 'sem leituras';
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
    if (min < 60) return `há ${min} min`;
    if (min < 1440) return `há ${Math.floor(min / 60)} h`;
    return `há ${Math.floor(min / 1440)} d`;
  }
}
