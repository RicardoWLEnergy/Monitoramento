import { Component, DestroyRef, OnChanges, computed, inject, input, output, signal } from '@angular/core';
import { DatePipe, DecimalPipe, I18nPluralPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Observable } from 'rxjs';
import { Download, ExternalLink, LucideAngularModule, Trash2, X } from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { plural } from '../../services/formato';
import { diasAtras, isoLocal } from '../../services/periodo';
import {
  CoberturaHistorico, ConfigAlertas, DadosUsina, ImportacaoHistorico, UsinaDetalhe, UsinasService,
} from '../../services/usinas.service';

const MESES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

type Secao = 'dados' | 'alertas' | 'esperado' | 'clientes' | 'historico' | 'apagar';

/** Fusos do Brasil (IANA). */
const FUSOS = ['America/Sao_Paulo', 'America/Bahia', 'America/Fortaleza', 'America/Recife', 'America/Belem',
  'America/Manaus', 'America/Cuiaba', 'America/Campo_Grande', 'America/Porto_Velho', 'America/Boa_Vista',
  'America/Rio_Branco', 'America/Noronha'];
interface Aviso { tipo: 'ok' | 'erro'; texto: string; }

const emAndamento = (i: ImportacaoHistorico | null | undefined) => i?.status === 'fila' || i?.status === 'importando';
/** De quanto em quanto tempo a tela pergunta o progresso da importação. */
const INTERVALO_PROGRESSO_MS = 5000;

/**
 * Aba "Configurações" (Admin e Colaborador).
 * - Dados da usina: vêm da plataforma no 1º cadastro; Admin e Colaborador corrigem
 * - Histórico de geração: pede a importação de dias anteriores; o servidor importa em segundo plano
 *   (pode fechar a página) e a tela mostra o progresso enquanto estiver aberta (Admin e Colaborador)
 * - Clientes vinculados: Admin e Colaborador
 * - Geração esperada (prognóstico): Admin e Colaborador; alertas: só o Admin altera
 * - Apagar usina: só o Admin (desativa; o histórico fica e volta se a SN for cadastrada de novo)
 */
@Component({
  selector: 'app-usina-config',
  imports: [DatePipe, DecimalPipe, I18nPluralPipe, FormsModule, RouterLink, LucideAngularModule],
  templateUrl: './usina-config.component.html',
  styleUrl: './usina-config.component.css',
})
export class UsinaConfigComponent implements OnChanges {
  private readonly api = inject(UsinasService);
  private readonly router = inject(Router);
  readonly auth = inject(AuthService);

  readonly usina = input.required<UsinaDetalhe>();
  readonly atualizada = output<UsinaDetalhe>();
  /** Avisa a tela da usina para recarregar os gráficos depois de importar. */
  readonly importado = output<void>();

  readonly icones = { Download, ExternalLink, Trash2, X };
  readonly meses = MESES;

  dados!: DadosUsina;
  fusos = FUSOS;
  alertas!: ConfigAlertas;
  esperado: (number | null)[] = Array(12).fill(null);

  readonly salvando = signal<Secao | null>(null);
  readonly aviso = signal<Partial<Record<Secao, Aviso | null>>>({});

  // ---------- Histórico ----------
  readonly hoje = isoLocal(new Date());
  readonly cobertura = signal<CoberturaHistorico | null>(null);
  periodo = { inicio: diasAtras(29), fim: isoLocal(new Date()), curvas: true };
  readonly atalhos = [
    { rotulo: '7 dias', dias: 7 }, { rotulo: '30 dias', dias: 30 },
    { rotulo: '90 dias', dias: 90 }, { rotulo: '12 meses', dias: 365 },
  ];

  readonly importacao = computed(() => this.cobertura()?.importacao ?? null);
  readonly importando = computed(() => emAndamento(this.importacao()));
  readonly progresso = computed(() => {
    const i = this.importacao();
    return i && i.passos_total ? Math.round((100 * i.passos_feitos) / i.passos_total) : 0;
  });
  private acompanhamento: ReturnType<typeof setInterval> | null = null;

  private idCarregado = 0;

  constructor() {
    inject(DestroyRef).onDestroy(() => this.pararAcompanhamento());
  }

  ngOnChanges(): void {
    const u = this.usina();
    this.dados = {
      nome: u.nome, endereco: u.endereco, cidade: u.cidade, uf: u.uf,
      latitude: u.latitude, longitude: u.longitude, potencia_kwp: u.potencia_kwp, fuso_horario: u.fuso_horario,
      inicio_operacao: u.inicio_operacao,
    };
    if (!this.fusos.includes(u.fuso_horario)) this.fusos = [u.fuso_horario, ...FUSOS];
    this.periodo = { ...this.periodo, inicio: this.desdeOInicio(this.periodo.inicio) };
    this.alertas = {
      alertas_ativos: u.alertas_ativos,
      limite_desempenho_pct: u.limite_desempenho_pct,
      minutos_sem_comunicacao: u.minutos_sem_comunicacao,
    };
    if (u.id !== this.idCarregado) {
      this.idCarregado = u.id;
      this.pararAcompanhamento();
      this.cobertura.set(null);
      this.atualizarCobertura();
      this.api.geracaoEsperada(u.id).subscribe(lista => {
        this.esperado = Array(12).fill(null);
        for (const item of lista) this.esperado[item.mes - 1] = item.energia_kwh;
      });
    }
  }

  get totalEsperado(): number {
    return this.esperado.reduce<number>((t, v) => t + (Number(v) || 0), 0);
  }

  // ---------- Histórico ----------
  usarAtalho(dias: number): void {
    this.periodo = { ...this.periodo, inicio: this.desdeOInicio(diasAtras(dias - 1)), fim: this.hoje };
  }

  /** A importação começa no início da operação (antes dele tudo seria zero). */
  desdeOInicio(data: string): string {
    const inicio = this.usina().inicio_operacao;
    return inicio && inicio > data ? inicio : data;
  }

  /** Estimativa: ~1 s por inversor por dia de curva + 1 s por inversor por mês de energia. */
  get estimativaTexto(): string {
    const ini = new Date(this.periodo.inicio), fim = new Date(this.periodo.fim);
    const dias = Math.max(0, Math.round((fim.getTime() - ini.getTime()) / 86_400_000) + 1);
    const meses = Math.max(1, (fim.getFullYear() - ini.getFullYear()) * 12 + fim.getMonth() - ini.getMonth() + 1);
    const inversores = this.cobertura()?.inversores || 1;
    const segundos = inversores * ((this.periodo.curvas ? dias : 0) + meses) + 2;
    return segundos < 60 ? `~${segundos} s` : `~${Math.ceil(segundos / 60)} min`;
  }

  importarHistorico(): void {
    const { inicio, fim, curvas } = this.periodo;
    this.salvando.set('historico');
    this.aviso.update(a => ({ ...a, historico: null }));
    this.api.importarHistorico(this.usina().id, inicio, fim, curvas).subscribe({
      next: c => {
        this.salvando.set(null);
        this.receberCobertura(c);
      },
      error: e => {
        this.salvando.set(null);
        this.aviso.update(a => ({ ...a, historico: { tipo: 'erro', texto: mensagemDeErro(e, 'Não foi possível importar.') } }));
      },
    });
  }

  /** Resumo de uma importação concluída. */
  resumoImportacao(i: ImportacaoHistorico): string {
    let texto = `${plural(i.dias_energia, 'dia', 'dias')} de energia`;
    if (i.curvas) texto += ` e ${plural(i.dias_curva, 'dia', 'dias')} de curva`;
    return texto;
  }

  private atualizarCobertura(): void {
    this.api.coberturaHistorico(this.usina().id).subscribe({ next: c => this.receberCobertura(c), error: () => {} });
  }

  /** Guarda a situação; enquanto houver importação em andamento, pergunta o progresso a cada 5 s. */
  private receberCobertura(c: CoberturaHistorico): void {
    const antes = this.cobertura()?.importacao;
    this.cobertura.set(c);
    if (emAndamento(c.importacao)) {
      this.acompanhamento ??= setInterval(() => this.atualizarCobertura(), INTERVALO_PROGRESSO_MS);
      return;
    }
    this.pararAcompanhamento();
    if (emAndamento(antes) && c.importacao?.id === antes?.id) this.importado.emit();   // terminou: recarrega os gráficos
  }

  private pararAcompanhamento(): void {
    if (this.acompanhamento) clearInterval(this.acompanhamento);
    this.acompanhamento = null;
  }

  // ---------- Demais seções ----------
  salvarDados(): void {
    const vazioViraNull = (v: number | null | string) => (v === '' || v === undefined ? null : v) as number | null;
    const dados = {
      ...this.dados, latitude: vazioViraNull(this.dados.latitude), longitude: vazioViraNull(this.dados.longitude),
      inicio_operacao: this.dados.inicio_operacao || null,
    };
    this.executar('dados', this.api.salvarDados(this.usina().id, dados), 'Dados salvos.');
  }

  salvarAlertas(): void {
    this.executar('alertas', this.api.salvarAlertas(this.usina().id, this.alertas), 'Alertas salvos.');
  }

  salvarEsperado(): void {
    const valores = this.esperado
      .map((v, i) => ({ mes: i + 1, energia_kwh: Number(v) }))
      .filter((_, i) => this.esperado[i] !== null && this.esperado[i] !== undefined && `${this.esperado[i]}` !== '');
    this.executar('esperado', this.api.salvarGeracaoEsperada(this.usina().id, valores), 'Geração esperada salva.',
      () => this.api.detalhe(this.usina().id).subscribe(u => this.atualizada.emit(u)));
  }

  desvincular(clienteId: number, nome: string): void {
    if (!confirm(`Desvincular ${nome} desta usina? Essa pessoa deixará de ver os dados dela.`)) return;
    const ids = (this.usina().clientes ?? []).map(c => c.id).filter(id => id !== clienteId);
    this.executar('clientes', this.api.definirClientes(this.usina().id, ids), `${nome} desvinculado(a).`);
  }

  /** Pede o nome da usina para confirmar (evita apagar a usina errada por engano). */
  apagarUsina(): void {
    const nome = this.usina().nome;
    const digitado = prompt(
      `Apagar a usina "${nome}"?\n\n` +
      'Ela some do sistema e os clientes perdem o acesso. O histórico fica guardado e volta ' +
      'se a SN de um inversor dela for cadastrada de novo.\n\nDigite o nome da usina para confirmar:');
    if (digitado === null) return;
    if (digitado.trim().toLowerCase() !== nome.trim().toLowerCase()) {
      this.aviso.update(a => ({ ...a, apagar: { tipo: 'erro', texto: 'O nome digitado não confere. Nada foi apagado.' } }));
      return;
    }
    this.salvando.set('apagar');
    this.api.apagar(this.usina().id).subscribe({
      next: () => this.router.navigate(['/usinas']),
      error: e => {
        this.salvando.set(null);
        this.aviso.update(a => ({ ...a, apagar: { tipo: 'erro', texto: mensagemDeErro(e, 'Não foi possível apagar.') } }));
      },
    });
  }

  /** Salva uma seção mostrando "salvando…", sucesso ou erro só naquela seção. */
  private executar(secao: Secao, chamada: Observable<unknown>, sucesso: string, depois?: () => void): void {
    this.salvando.set(secao);
    this.aviso.update(a => ({ ...a, [secao]: null }));
    chamada.subscribe({
      next: r => {
        this.salvando.set(null);
        this.aviso.update(a => ({ ...a, [secao]: { tipo: 'ok', texto: sucesso } }));
        if (r && typeof r === 'object' && 'id' in r) this.atualizada.emit(r as UsinaDetalhe);
        depois?.();
      },
      error: e => {
        this.salvando.set(null);
        this.aviso.update(a => ({ ...a, [secao]: { tipo: 'erro', texto: mensagemDeErro(e, 'Não foi possível salvar.') } }));
      },
    });
  }
}
