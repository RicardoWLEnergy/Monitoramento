import { Component, OnChanges, inject, input, output, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Observable } from 'rxjs';
import { Download, ExternalLink, LucideAngularModule, Trash2, X } from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { CoberturaHistorico, ConfigAlertas, UsinaDetalhe, UsinasService } from '../../services/usinas.service';

const MESES = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];

type Secao = 'alertas' | 'esperado' | 'clientes' | 'historico' | 'apagar';
interface Aviso { tipo: 'ok' | 'erro'; texto: string; }

const isoLocal = (d: Date) => d.toLocaleDateString('sv-SE');   // AAAA-MM-DD no fuso local
const diasAtras = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return isoLocal(d); };

/**
 * Aba "Configurações" (Admin e Colaborador).
 * - Dados da usina: vêm da plataforma (somente leitura)
 * - Histórico de geração: importar dias anteriores da plataforma (Admin e Colaborador)
 * - Clientes vinculados: Admin e Colaborador
 * - Geração esperada e alertas: só o Admin altera
 * - Apagar usina: só o Admin (desativa; o histórico fica e volta se a SN for cadastrada de novo)
 */
@Component({
  selector: 'app-usina-config',
  imports: [DecimalPipe, FormsModule, RouterLink, LucideAngularModule],
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

  private idCarregado = 0;

  ngOnChanges(): void {
    const u = this.usina();
    this.alertas = {
      alertas_ativos: u.alertas_ativos,
      limite_desempenho_pct: u.limite_desempenho_pct,
      minutos_sem_comunicacao: u.minutos_sem_comunicacao,
    };
    if (u.id !== this.idCarregado) {
      this.idCarregado = u.id;
      this.api.coberturaHistorico(u.id).subscribe({ next: c => this.cobertura.set(c), error: () => {} });
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
    this.periodo = { ...this.periodo, inicio: diasAtras(dias - 1), fim: this.hoje };
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
      next: r => {
        this.salvando.set(null);
        this.cobertura.set(r.cobertura);
        let texto = `Importado: ${r.dias_energia} dia(s) de energia`;
        if (curvas) texto += ` e ${r.dias_curva} dia(s) de curva (${r.leituras} leituras)`;
        texto += r.falhas.length ? `. ${r.falhas.length} falha(s): ${r.falhas.slice(0, 2).join('; ')}` : '.';
        this.aviso.update(a => ({ ...a, historico: { tipo: r.falhas.length ? 'erro' : 'ok', texto } }));
        this.importado.emit();
      },
      error: e => {
        this.salvando.set(null);
        this.aviso.update(a => ({ ...a, historico: { tipo: 'erro', texto: mensagemDeErro(e, 'Não foi possível importar.') } }));
      },
    });
  }

  dataBR(iso: string | null): string {
    return iso ? iso.split('-').reverse().join('/') : '—';
  }

  // ---------- Demais seções ----------
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
