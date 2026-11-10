import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { forkJoin, map } from 'rxjs';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import {
  ArrowLeft, CalendarDays, ChartLine, Clock, Cpu, ExternalLink, Gauge, LucideAngularModule, MapPin, Settings, Zap,
} from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { GraficosService, echarts } from '../../services/graficos.service';
import {
  CLASSE_STATUS, Curva, Inversor, MesGeracao, ROTULO_STATUS, UsinaDetalhe, UsinasService,
} from '../../services/usinas.service';
import { UsinaConfigComponent } from './usina-config.component';

type Aba = 'geracao' | 'configuracoes';

const hojeIso = () => new Date().toLocaleDateString('sv-SE');   // AAAA-MM-DD no fuso local

/** Detalhe da usina: aba Geração (todos) e aba Configurações (Admin/Colaborador). */
@Component({
  selector: 'app-usina-detalhe',
  imports: [DecimalPipe, RouterLink, NgxEchartsDirective, LucideAngularModule, UsinaConfigComponent],
  providers: [provideEchartsCore({ echarts })],
  templateUrl: './usina-detalhe.component.html',
  styleUrl: './usina-detalhe.component.css',
})
export class UsinaDetalheComponent {
  private readonly api = inject(UsinasService);
  private readonly graficos = inject(GraficosService);
  private readonly router = inject(Router);
  private readonly rota = inject(ActivatedRoute);
  readonly auth = inject(AuthService);

  readonly icones = { ArrowLeft, CalendarDays, ChartLine, Clock, Cpu, ExternalLink, Gauge, MapPin, Settings, Zap };
  readonly rotuloStatus = ROTULO_STATUS;
  readonly classeStatus = CLASSE_STATUS;

  private readonly abaUrl = toSignal(
    this.rota.queryParamMap.pipe(map(q => (q.get('aba') === 'configuracoes' ? 'configuracoes' : 'geracao') as Aba)),
    { initialValue: 'geracao' as Aba },
  );
  /** Configurações só para a equipe; cliente sempre vê a aba Geração. */
  readonly aba = computed<Aba>(() => (this.auth.eEquipe() ? this.abaUrl() : 'geracao'));

  readonly usina = signal<UsinaDetalhe | null>(null);
  readonly inversores = signal<Inversor[]>([]);
  readonly historico = signal<MesGeracao[]>([]);
  readonly curva = signal<Curva | null>(null);
  readonly dataCurva = signal(hojeIso());
  readonly hoje = hojeIso();

  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);
  readonly historicoComoTabela = signal(false);

  private id = 0;

  readonly resumo = computed(() => {
    const u = this.usina();
    if (!u) return null;
    const pontos = this.curva()?.pontos ?? [];
    return {
      usoPct: u.potencia_kwp ? (u.potencia_atual_kw / u.potencia_kwp) * 100 : 0,
      produtividade: u.potencia_kwp ? u.geracao_hoje_kwh / u.potencia_kwp : 0,
      desempenhoMes: u.esperado_mes_kwh ? (u.geracao_mes_kwh / u.esperado_mes_kwh) * 100 : null,
      picoKw: Math.max(0, ...pontos.map(p => p.kw)),
    };
  });
  readonly temEsperado = computed(() => this.historico().some(m => m.esperado_kwh > 0));

  readonly opcoesCurva = computed(() => this.graficos.curvaPotencia(this.curva()?.pontos ?? []));
  readonly opcoesHistorico = computed(() => this.graficos.geracaoMensal(this.historico()));

  constructor() {
    this.rota.paramMap.pipe(takeUntilDestroyed()).subscribe(p => {
      this.id = Number(p.get('id'));
      this.carregar();
    });
  }

  carregar(): void {
    this.carregando.set(true);
    this.erro.set(null);
    forkJoin({
      usina: this.api.detalhe(this.id),
      inversores: this.api.inversores(this.id),
      historico: this.api.geracaoMensal(this.id),
    }).subscribe({
      next: r => {
        this.usina.set(r.usina);
        this.inversores.set(r.inversores);
        this.historico.set(r.historico);
        this.carregando.set(false);
      },
      error: e => {
        this.usina.set(null);
        this.erro.set(e?.status === 404 ? null : mensagemDeErro(e, 'Não foi possível carregar a usina.'));
        this.carregando.set(false);
      },
    });
    this.carregarCurva();
  }

  carregarCurva(): void {
    this.api.curva(this.id, this.dataCurva()).subscribe({
      next: c => this.curva.set(c),
      error: () => this.curva.set(null),
    });
  }

  mudarDia(data: string): void {
    if (!data) return;
    this.dataCurva.set(data);
    this.carregarCurva();
  }

  irParaAba(aba: Aba): void {
    this.router.navigate([], {
      relativeTo: this.rota, queryParams: { aba: aba === 'geracao' ? null : aba }, replaceUrl: true,
    });
  }

  /** Chamado pela aba Configurações depois de salvar. */
  aoAtualizar(u: UsinaDetalhe): void {
    this.usina.set(u);
    this.api.geracaoMensal(this.id).subscribe(h => this.historico.set(h));
  }

  desempenhoMes(m: MesGeracao): number | null {
    return m.esperado_kwh > 0 ? (m.gerado_kwh / m.esperado_kwh) * 100 : null;
  }

  dataHora(iso: string | null): string {
    if (!iso) return 'sem leituras';
    return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
}
