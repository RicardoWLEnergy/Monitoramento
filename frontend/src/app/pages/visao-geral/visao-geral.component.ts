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
  readonly opcoesCurva = computed(() => this.graficos.curvaPotencia(this.dados()?.curva_hoje ?? []));
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

  ultimaLeitura(iso: string | null): string {
    if (!iso) return 'sem leituras';
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
    if (min < 60) return `há ${min} min`;
    if (min < 1440) return `há ${Math.floor(min / 60)} h`;
    return `há ${Math.floor(min / 1440)} d`;
  }
}
