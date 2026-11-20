import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { Subscription } from 'rxjs';
import { DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Check, ChevronDown, CloudOff, LucideAngularModule, MapPin, RefreshCw } from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import { dataBR, diaMesBR, diasEntre, hojeIso } from '../../services/periodo';
import { EtapaProjeto, Projeto, ProjetoService } from '../../services/projeto.service';
import { EtapaDetalheComponent } from './etapa-detalhe.component';

const MEDIA_CELULAR = '(max-width: 760px)';

/**
 * Meu projeto: o cliente acompanha a instalação da usina.
 * - Topo: a usina e a previsão de conclusão.
 * - Etapas clicáveis (linha contínua = feito; tracejada = falta). A escolhida abre o painel com
 *   "o que foi feito / está acontecendo / vai acontecer", datas e documentos.
 * - No celular: lista vertical; o painel abre embaixo da etapa tocada.
 */
@Component({
  selector: 'app-projeto',
  imports: [DecimalPipe, FormsModule, NgTemplateOutlet, LucideAngularModule, EtapaDetalheComponent],
  templateUrl: './projeto.component.html',
  styleUrl: './projeto.component.css',
})
export class ProjetoComponent {
  private readonly api = inject(ProjetoService);
  private readonly rota = inject(ActivatedRoute);
  private readonly router = inject(Router);
  readonly auth = inject(AuthService);

  /** Equipe: ID do cliente consultado (?id_cliente= no endereço). O cliente sempre vê o próprio. */
  readonly idConsulta = signal<string | null>(null);
  campoId = '';
  /** Busca em andamento: uma nova (outro ID ou "Tentar de novo") cancela a anterior. */
  private busca: Subscription | null = null;
  readonly icones = { Check, ChevronDown, CloudOff, MapPin, RefreshCw };
  readonly dataBR = dataBR;

  readonly projeto = signal<Projeto | null>(null);
  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);
  readonly escolhida = signal(0);
  /** No celular, tocar de novo na etapa aberta fecha o painel. */
  readonly aberta = signal(true);
  readonly celular = signal(window.matchMedia(MEDIA_CELULAR).matches);

  readonly etapas = computed(() => this.projeto()?.etapas ?? []);
  readonly indiceAtual = computed(() => this.etapas().findIndex(e => e.status === 'andamento'));
  readonly concluidas = computed(() => this.etapas().filter(e => e.status === 'concluida').length);
  readonly concluido = computed(() => this.etapas().length > 0 && this.concluidas() === this.etapas().length);

  readonly faltam = computed(() => {
    const p = this.projeto();
    if (!p) return '';
    if (this.concluido()) return 'Usina pronta para gerar';
    if (!p.previsao_conclusao) return 'Os prazos aparecem aqui conforme o projeto avança';
    const dias = diasEntre(hojeIso(), p.previsao_conclusao);
    if (dias > 1) return `Faltam ${dias} dias`;
    if (dias === 1) return 'Falta 1 dia';
    return dias === 0 ? 'Previsto para hoje' : 'Prazo em revisão pela equipe';
  });

  constructor() {
    const media = window.matchMedia(MEDIA_CELULAR);
    const mudou = (ev: MediaQueryListEvent) => { this.celular.set(ev.matches); this.aberta.set(true); };
    media.addEventListener('change', mudou);
    inject(DestroyRef).onDestroy(() => { media.removeEventListener('change', mudou); this.busca?.unsubscribe(); });
    this.rota.queryParamMap.subscribe(q => {
      const id = this.auth.eEquipe() ? q.get('id_cliente') : null;
      if (id !== this.idConsulta()) this.projeto.set(null);   // outro cliente: não mostra o projeto anterior
      this.idConsulta.set(id);
      this.campoId = id ?? '';
      this.carregar();
    });
  }

  /** Equipe: consulta o projeto de um cliente pelo ID. */
  consultar(): void {
    this.router.navigate([], { queryParams: { id_cliente: this.campoId.trim() || null } });
  }

  carregar(): void {
    this.carregando.set(true);
    this.erro.set(null);
    if (this.auth.eEquipe() && !this.idConsulta()) {   // equipe ainda não escolheu um cliente
      this.projeto.set(null);
      this.carregando.set(false);
      return;
    }
    this.busca?.unsubscribe();
    this.busca = this.api.meuProjeto(this.idConsulta()).subscribe({
      next: p => {
        this.projeto.set(p);
        // Abre na etapa atual (ou na última, se tudo já estiver concluído)
        const atual = p?.etapas.findIndex(e => e.status === 'andamento') ?? -1;
        this.escolhida.set(atual >= 0 ? atual : Math.max(0, (p?.etapas.length ?? 1) - 1));
        this.carregando.set(false);
      },
      error: e => { this.erro.set(mensagemDeErro(e, 'Não foi possível carregar o seu projeto.')); this.carregando.set(false); },
    });
  }

  escolher(i: number): void {
    if (i < 0 || i >= this.etapas().length) return;
    this.escolhida.set(i);
    this.aberta.set(true);
  }

  /** Celular: tocar na etapa aberta fecha; em outra, abre. */
  tocar(i: number): void {
    if (i === this.escolhida() && this.aberta()) this.aberta.set(false);
    else this.escolher(i);
  }

  /** Setas do teclado trocam de etapa. */
  teclado(ev: KeyboardEvent, i: number): void {
    const passo = ({ ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 } as Record<string, number>)[ev.key];
    if (!passo) return;
    ev.preventDefault();
    const alvo = i + passo;
    if (alvo < 0 || alvo >= this.etapas().length) return;
    this.escolher(alvo);
    document.getElementById(`aba-${alvo}`)?.focus();
  }

  /** Legenda curta de cada etapa. */
  quando(e: EtapaProjeto): string {
    if (e.status === 'concluida') return e.fim ? `Concluída em ${diaMesBR(e.fim)}` : 'Concluída';
    if (e.status === 'andamento') return e.previsao_fim ? `Em andamento, até ${diaMesBR(e.previsao_fim)}` : 'Em andamento';
    if (e.previsao_inicio && e.previsao_fim) return `Previsão: ${diaMesBR(e.previsao_inicio)} a ${diaMesBR(e.previsao_fim)}`;
    return 'Previsão a definir';
  }

  /** Barrinha do celular: quanto de cada etapa já foi (0–100). */
  avanco(e: EtapaProjeto): number {
    if (e.status === 'concluida') return 100;
    if (e.status === 'proxima' || !e.inicio || !e.previsao_fim) return 0;
    const total = diasEntre(e.inicio, e.previsao_fim);
    return total > 0 ? Math.min(90, Math.max(10, (diasEntre(e.inicio, hojeIso()) / total) * 100)) : 50;
  }
}
