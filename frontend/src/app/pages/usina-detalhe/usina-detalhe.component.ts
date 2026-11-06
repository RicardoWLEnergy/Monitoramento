import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { map } from 'rxjs';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import {
  ArrowLeft, CalendarDays, ChartLine, Clock, Cpu, Gauge, LucideAngularModule, MapPin, Settings, Zap,
} from 'lucide-angular';

import { TemaService } from '../../core/tema.service';
import { UsinasService } from '../../core/usinas.service';
import { StatusUsina } from '../../core/usinas.mock';
import { curvaDoDia, historico12Meses, inversores } from '../../core/usina-detalhe.mock';
import { coresDoTema, echarts } from '../../shared/graficos/tema-grafico';
import { opcoesCurvaPotencia, opcoesGeracaoMensal } from '../../shared/graficos/opcoes-graficos';
import { UsinaConfigComponent } from './usina-config.component';

type Aba = 'geracao' | 'configuracoes';

/** Detalhe da usina, em duas abas: Geração (KPIs, gráficos, inversores) e Configurações. */
@Component({
  selector: 'app-usina-detalhe',
  imports: [DecimalPipe, RouterLink, NgxEchartsDirective, LucideAngularModule, UsinaConfigComponent],
  providers: [provideEchartsCore({ echarts })],
  templateUrl: './usina-detalhe.component.html',
  styleUrl: './usina-detalhe.component.css',
})
export class UsinaDetalheComponent {
  private readonly servico = inject(UsinasService);
  private readonly tema = inject(TemaService);
  private readonly router = inject(Router);
  private readonly rota = inject(ActivatedRoute);

  private readonly id = toSignal(this.rota.paramMap.pipe(map(p => Number(p.get('id')))), { initialValue: 0 });

  /** Aba ativa vem da URL (?aba=configuracoes), para poder linkar direto. */
  readonly aba = toSignal(
    this.rota.queryParamMap.pipe(map(q => (q.get('aba') === 'configuracoes' ? 'configuracoes' : 'geracao') as Aba)),
    { initialValue: 'geracao' as Aba },
  );

  readonly icones = { ArrowLeft, CalendarDays, ChartLine, Clock, Cpu, Gauge, MapPin, Settings, Zap };
  readonly rotuloStatus: Record<StatusUsina, string> = { online: 'Online', alerta: 'Alerta', offline: 'Offline' };
  readonly classeStatus: Record<StatusUsina, string> = { online: 'ok', alerta: 'warn', offline: 'danger' };

  /** Alterna o histórico entre gráfico e tabela (acessibilidade / leitura exata). */
  readonly historicoComoTabela = signal(false);

  readonly usina = computed(() => { this.servico.usinas(); return this.servico.porId(this.id()); });
  readonly curva = computed(() => { const u = this.usina(); return u ? curvaDoDia(u) : []; });
  readonly historico = computed(() => { const u = this.usina(); return u ? historico12Meses(u) : []; });
  readonly inversores = computed(() => { const u = this.usina(); return u ? inversores(u) : []; });

  readonly resumo = computed(() => {
    const u = this.usina();
    if (!u) return null;
    return {
      usoPct: (u.potenciaAtualKw / u.potenciaKwp) * 100,
      produtividade: u.geracaoHojeKwh / u.potenciaKwp,
      desempenhoMes: (u.geracaoMesKwh / u.esperadoMesKwh) * 100,
      picoKw: Math.max(0, ...this.curva().map(p => p.kw)),
    };
  });

  /** Cores lidas do tema atual — recalculadas quando o tema muda. */
  private readonly cores = computed(() => { this.tema.tema(); return coresDoTema(); });

  readonly opcoesCurva = computed(() => opcoesCurvaPotencia(this.curva(), this.cores()));
  readonly opcoesHistorico = computed(() => opcoesGeracaoMensal(this.historico(), this.cores()));

  irParaAba(aba: Aba): void {
    this.router.navigate([], {
      relativeTo: this.rota,
      queryParams: { aba: aba === 'geracao' ? null : aba },
      replaceUrl: true,
    });
  }

  desempenhoMes(gerado: number, esperado: number): number { return (gerado / esperado) * 100; }

  ultimaLeitura(iso: string): string {
    return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
}
