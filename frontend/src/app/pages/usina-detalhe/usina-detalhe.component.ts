import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { DecimalPipe, I18nPluralPipe } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed, toSignal } from '@angular/core/rxjs-interop';
import { forkJoin, map } from 'rxjs';
import { NgxEchartsDirective, provideEchartsCore } from 'ngx-echarts';
import {
  ChevronLeft, ChevronRight,
  ArrowLeft, CalendarDays, ChartLine, Clock, Cloud, CloudRain, Cpu, ExternalLink, Gauge, LucideAngularModule, MapPin,
  Settings, Sun, TrendingUp, Zap,
} from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { GraficosService, echarts, numeroBR, textoClima } from '../../services/graficos.service';
import {
  ATUALIZAR_A_CADA_MS, CardKpi, ESCALAS, Escala, agruparPorMes, cardsDoPeriodo, dataBR, deslocar, energiaBR, hojeIso,
  intervaloDa, pctBR, pctDoEsperado, picoDaCurva, resumoPeriodo,
} from '../../services/periodo';
import {
  CLASSE_STATUS, Curva, DiaGeracao, GeracaoPeriodo, Inversor, MesGeracao, ROTULO_CLIMA, ROTULO_STATUS, UsinaDetalhe,
  UsinasService,
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
  /** Energia e esperado do dia escolhido no modo Dia (só quando não é hoje). */
  readonly dadosDia = signal<DiaGeracao | null>(null);

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
  private ultimaAtualizacao = 0;

  /** Cards de hoje (modo Dia no dia atual). */
  readonly resumo = computed(() => {
    const u = this.usina();
    if (!u) return null;
    return {
      usoPct: u.potencia_kwp ? (u.potencia_atual_kw / u.potencia_kwp) * 100 : 0,
      hojePct: pctDoEsperado(u.geracao_hoje_kwh, u.esperado_hoje_kwh),
      picoKw: picoDaCurva(this.curva()?.pontos ?? [])?.kw ?? 0,
    };
  });

  /** Cards de outro dia ou do período escolhido no gráfico (null = cards de hoje). */
  readonly cardsVariaveis = computed<CardKpi[] | null>(() => {
    if (this.modo() === 'periodo') {
      return cardsDoPeriodo(this.resumoPeriodo(), !this.periodo() && !this.erroPeriodo(),
        { total: CalendarDays, media: ChartLine, esperado: Gauge, melhor: TrendingUp });
    }
    if (this.dataCurva() === this.hoje) return null;
    const d = this.dadosDia();
    const pico = picoDaCurva(this.curva()?.pontos ?? []);
    const cl = this.curva()?.clima;
    return [
      { rotulo: 'Geração do dia', valor: d?.kwh != null ? energiaBR(d.kwh) : '—', detalhe: dataBR(this.dataCurva()), icone: CalendarDays },
      { rotulo: 'Pico do dia', valor: pico ? `${numeroBR(pico.kw, 1)} kW` : '—', detalhe: pico ? `às ${pico.hora}` : 'sem leituras', icone: TrendingUp },
      { rotulo: 'Gerado × esperado', valor: pctBR(pctDoEsperado(d?.kwh, d?.esperado_kwh)),
        detalhe: d?.esperado_kwh ? `esperado: ${energiaBR(d.esperado_kwh)}` : 'sem geração esperada cadastrada', icone: Gauge },
      { rotulo: 'Clima do dia', valor: (cl && ROTULO_CLIMA[cl.condicao]) || '—',
        detalhe: !cl ? 'sem dado de clima' : cl.chuva_mm >= 1 ? `${numeroBR(cl.chuva_mm)} mm de chuva` : 'sem chuva',
        icone: (cl && this.iconeClima[cl.condicao]) || Cloud },
    ];
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
    // Atualiza sozinha a cada 5 min (o ritmo da coleta); confere a cada minuto, só com a aba visível
    const relogio = setInterval(() => this.atualizarSeVencido(), 60_000);
    inject(DestroyRef).onDestroy(() => clearInterval(relogio));
  }

  /** Atualização silenciosa: sem "Carregando..." e, se falhar, mantém o que está na tela. */
  private atualizarSeVencido(): void {
    if (document.hidden || !this.usina() || this.aba() !== 'geracao'
        || Date.now() - this.ultimaAtualizacao < ATUALIZAR_A_CADA_MS) return;
    this.ultimaAtualizacao = Date.now();
    forkJoin({ usina: this.api.detalhe(this.id), inversores: this.api.inversores(this.id) }).subscribe({
      next: r => { this.usina.set(r.usina); this.inversores.set(r.inversores); },
      error: () => undefined,
    });
    if (this.dataCurva() === this.hoje) this.carregarCurva();
    if (this.modo() === 'periodo' && this.fimAteHoje() === this.hoje) this.carregarPeriodo();
  }

  carregar(): void {
    this.ultimaAtualizacao = Date.now();
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
    const data = this.dataCurva();
    this.api.curva(this.id, data).subscribe({
      next: c => this.curva.set(c),
      error: () => this.curva.set(null),
    });
    if (data === this.hoje) return;
    this.api.geracaoDiaria(this.id, data, data).subscribe({
      next: p => this.dadosDia.set(p.dias[0] ?? null),
      error: () => this.dadosDia.set(null),
    });
  }

  mudarDia(data: string): void {
    if (!data) return;
    this.dataCurva.set(data);
    this.dadosDia.set(null);
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
