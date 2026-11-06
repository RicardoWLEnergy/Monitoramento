import { Component, computed, inject } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import {
  Activity, CalendarDays, Gauge, LucideAngularModule, TriangleAlert, WifiOff, Zap,
} from 'lucide-angular';

import { TemaService } from '../../core/tema.service';
import { UsinasService } from '../../core/usinas.service';
import { Usina } from '../../core/usinas.mock';
import { coresDoTema, echarts } from '../../shared/graficos/tema-grafico';
import { opcoesCurvaPotencia, opcoesGeracaoMensal } from '../../shared/graficos/opcoes-graficos';

/** Visão geral: dashboard da carteira — o que importa saber de relance. */
@Component({
  selector: 'app-visao-geral',
  imports: [DecimalPipe, RouterLink, NgxEchartsDirective, LucideAngularModule],
  providers: [provideEchartsCore({ echarts })],
  templateUrl: './visao-geral.component.html',
  styleUrl: './visao-geral.component.css',
})
export class VisaoGeralComponent {
  private readonly servico = inject(UsinasService);
  private readonly tema = inject(TemaService);

  readonly icones = { Activity, CalendarDays, Gauge, TriangleAlert, WifiOff, Zap };

  readonly hoje = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' });

  readonly kpis = computed(() => {
    const u = this.servico.usinas();
    const soma = (f: (x: Usina) => number) => u.reduce((t, x) => t + f(x), 0);
    return {
      geracaoHojeKwh: soma(x => x.geracaoHojeKwh),
      geracaoMesMwh: soma(x => x.geracaoMesKwh) / 1000,
      desempenhoMes: (soma(x => x.geracaoMesKwh) / soma(x => x.esperadoMesKwh)) * 100,
      potenciaAtualKw: soma(x => x.potenciaAtualKw),
      potenciaInstaladaKwp: soma(x => x.potenciaKwp),
      total: u.length,
      online: u.filter(x => x.status === 'online').length,
      alerta: u.filter(x => x.status === 'alerta').length,
      offline: u.filter(x => x.status === 'offline').length,
    };
  });

  /** Usinas offline primeiro, depois em alerta. */
  readonly atencao = computed(() =>
    this.servico.usinas()
      .filter(u => u.status !== 'online')
      .sort((a, b) => (a.status === 'offline' ? -1 : 1) - (b.status === 'offline' ? -1 : 1)));

  /** As 5 usinas mais distantes do esperado no mês. */
  readonly menorDesempenho = computed(() =>
    this.servico.usinas()
      .map(u => ({ usina: u, pct: (u.geracaoMesKwh / u.esperadoMesKwh) * 100 }))
      .sort((a, b) => a.pct - b.pct)
      .slice(0, 5));

  private readonly cores = computed(() => { this.tema.tema(); return coresDoTema(); });

  readonly opcoesCurva = computed(() => opcoesCurvaPotencia(this.servico.curvaCarteira(), this.cores()));
  readonly opcoesMensal = computed(() => opcoesGeracaoMensal(this.servico.historicoCarteira(), this.cores(), 'MWh'));

  ultimaLeitura(iso: string): string {
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
    if (min < 60) return `há ${min} min`;
    if (min < 1440) return `há ${Math.floor(min / 60)} h`;
    return `há ${Math.floor(min / 1440)} d`;
  }
}
