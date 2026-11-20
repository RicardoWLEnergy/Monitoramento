import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe, I18nPluralPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { forkJoin, map } from 'rxjs';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import {
  ChevronLeft, ChevronRight,
  ArrowLeft, CalendarDays, ChartLine, Clock, Cloud, CloudRain, Cpu, ExternalLink, Gauge, LucideAngularModule, MapPin,
  Settings, Sun, Zap,
} from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { GraficosService, echarts, textoClima } from '../../services/graficos.service';
import {
  ESCALAS, Escala, agruparPorMes, deslocar, hojeIso, intervaloDa, resumoPeriodo,
} from '../../services/periodo';
import {
  CLASSE_STATUS, Curva, GeracaoPeriodo, Inversor, MesGeracao, ROTULO_STATUS, UsinaDetalhe, UsinasService,
} from '../../services/usinas.service';
import { UsinaConfigComponent } from './usina-config.component';

type Aba = 'geracao' | 'configuracoes';
type Modo = 'dia' | 'periodo';

/** Detalhe da usina: aba Geração (todos) e aba Configurações (Admin/Colaborador). */
@Component({
  selector: 'app-usina-detalhe',
  imports: [DecimalPipe, I18nPluralPipe, RouterLink, NgxEchartsDirective, LucideAngularModule, UsinaConfigComponent],
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

  readonly icones = { ChevronLeft, ChevronRight, ArrowLeft, CalendarDays, ChartLine, Clock, Cpu, ExternalLink, Gauge, MapPin, Settings, Zap };
  readonly iconeClima = { ensolarado: Sun, nublado: Cloud, chuvoso: CloudRain };
  readonly textoClima = textoClima;
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

  // Gráfico de cima: "Dia" (curva de potência) ou "Período" (energia de cada dia)
  readonly modo = signal<Modo>('dia');
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
  readonly podeAvancar = computed(() => this.intervalo().fim < this.hoje);
  readonly periodo = signal<GeracaoPeriodo | null>(null);
  readonly erroPeriodo = signal<string | null>(null);

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
      // Gerado no mês × esperado ATÉ HOJE (proporcional aos dias passados), não o mês inteiro
      desempenhoMes: u.esperado_ate_hoje_kwh ? (u.geracao_mes_kwh / u.esperado_ate_hoje_kwh) * 100 : null,
      picoKw: Math.max(0, ...pontos.map(p => p.kw)),
    };
  });
  readonly temEsperado = computed(() => this.historico().some(m => m.esperado_kwh > 0));

  readonly resumoPeriodo = computed(() => resumoPeriodo(this.periodo()?.dias ?? []));
  readonly opcoesPeriodo = computed(() => this.escala() === 'ano'
    ? this.graficos.geracaoMensal(
      agruparPorMes(this.periodo()?.dias ?? [], Number(this.intervalo().inicio.slice(0, 4)), this.hoje), 'kWh')
    : this.graficos.geracaoDiaria(this.periodo()?.dias ?? [], this.hoje));

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
    if (this.modo() === 'periodo') this.carregarPeriodo();
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

  mudarModo(modo: Modo): void {
    this.modo.set(modo);
    if (modo === 'periodo' && !this.periodo()) this.carregarPeriodo();
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
    return this.intervalo().fim < this.hoje ? this.intervalo().fim : this.hoje;
  }

  carregarPeriodo(): void {
    this.erroPeriodo.set(null);
    this.api.geracaoDiaria(this.id, this.intervalo().inicio, this.fimAteHoje()).subscribe({
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
    return m.esperado_ate_hoje_kwh > 0 ? (m.gerado_kwh / m.esperado_ate_hoje_kwh) * 100 : null;
  }

  dataHora(iso: string | null): string {
    if (!iso) return 'sem leituras';
    return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  }
}
