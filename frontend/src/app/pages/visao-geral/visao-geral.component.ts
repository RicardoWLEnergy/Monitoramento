import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe, I18nPluralPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import {
  Activity, CalendarDays, Gauge, LucideAngularModule, TriangleAlert, WifiOff, Zap,
} from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { Dashboard, DashboardService } from '../../services/dashboard.service';
import { GraficosService, echarts } from '../../services/graficos.service';
import { atalhosPeriodo, hojeIso, resumoPeriodo } from '../../services/periodo';
import { GeracaoPeriodo, PontoCurva } from '../../services/usinas.service';

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

  readonly icones = { Activity, CalendarDays, Gauge, TriangleAlert, WifiOff, Zap };
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
  readonly atalhos = atalhosPeriodo();
  readonly inicioPeriodo = signal(this.atalhos[1].inicio);
  readonly fimPeriodo = signal(this.atalhos[1].fim);
  readonly periodo = signal<GeracaoPeriodo | null>(null);
  readonly erroPeriodo = signal<string | null>(null);
  readonly resumoPeriodo = computed(() => resumoPeriodo(this.periodo()?.dias ?? []));

  readonly pontosCurva = computed(() => this.curva() ?? this.dados()?.curva_hoje ?? []);
  readonly opcoesCurva = computed(() => this.graficos.curvaPotencia(this.pontosCurva()));
  readonly opcoesPeriodo = computed(() => this.graficos.geracaoDiaria(this.periodo()?.dias ?? [], this.hojeIso));
  readonly opcoesMensal = computed(() => this.graficos.geracaoMensal(this.dados()?.geracao_mensal ?? [], 'MWh'));

  constructor() {
    this.carregar();
  }

  carregar(): void {
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
    if (data === this.hojeIso) { this.curva.set(null); return; }
    this.api.curva(data).subscribe({ next: c => this.curva.set(c.pontos), error: () => this.curva.set([]) });
  }

  mudarPeriodo(inicio: string, fim: string): void {
    if (!inicio || !fim) return;
    this.inicioPeriodo.set(inicio);
    this.fimPeriodo.set(fim);
    this.carregarPeriodo();
  }

  carregarPeriodo(): void {
    this.erroPeriodo.set(null);
    this.api.geracaoDiaria(this.inicioPeriodo(), this.fimPeriodo()).subscribe({
      next: p => this.periodo.set(p),
      error: e => {
        this.periodo.set(null);
        this.erroPeriodo.set(mensagemDeErro(e, 'Não foi possível carregar o período.'));
      },
    });
  }

  /** Clique numa barra do período: abre a curva de potência daquele dia. */
  abrirDia(indice: number | undefined): void {
    const dia = indice === undefined ? null : this.periodo()?.dias[indice];
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
