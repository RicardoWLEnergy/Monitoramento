import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe, I18nPluralPipe } from '@angular/common';
import { toObservable, toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { catchError, debounceTime, of, switchMap, tap } from 'rxjs';
import { ChartLine, ChevronLeft, ChevronRight, LucideAngularModule, Search, Settings } from 'lucide-angular';

import { AuthService, mensagemDeErro } from '../../services/auth.service';
import {
  CLASSE_STATUS, Pagina, ROTULO_STATUS, ResumoUsinas, StatusUsina, UsinaLista, UsinasService,
} from '../../services/usinas.service';

type Coluna = 'nome' | 'fabricante' | 'potencia_kwp' | 'potencia_atual_kw' | 'geracao_hoje_kwh' | 'status';

const POR_PAGINA = 20;   // igual ao PAGE_SIZE da API

/** Usinas: lista com busca, filtros, ordenação e paginação feitos na API. */
@Component({
  selector: 'app-usinas',
  imports: [DecimalPipe, I18nPluralPipe, RouterLink, LucideAngularModule],
  templateUrl: './usinas.component.html',
  styleUrl: './usinas.component.css',
})
export class UsinasComponent {
  private readonly api = inject(UsinasService);
  readonly auth = inject(AuthService);

  readonly icones = { ChartLine, ChevronLeft, ChevronRight, Search, Settings };
  readonly rotuloStatus = ROTULO_STATUS;
  readonly classeStatus = CLASSE_STATUS;
  readonly fabricantes = [{ valor: 'weg', rotulo: 'WEG' }, { valor: 'foxess', rotulo: 'FoxESS' }, { valor: 'huawei', rotulo: 'Huawei' }];

  // ---------- Filtros ----------
  readonly busca = signal('');
  readonly status = signal<StatusUsina | null>(null);
  readonly fabricante = signal<string | null>(null);
  readonly ordem = signal<{ coluna: Coluna; asc: boolean }>({ coluna: 'nome', asc: true });
  readonly pagina = signal(1);

  readonly carregando = signal(true);
  readonly erro = signal<string | null>(null);

  private readonly filtro = computed(() => ({
    busca: this.busca().trim(),
    status: this.status(),
    fabricante: this.fabricante(),
    ordem: (this.ordem().asc ? '' : '-') + this.ordem().coluna,
    page: this.pagina(),
  }));

  /** Recarrega a lista sempre que um filtro muda (com uma pequena espera para a digitação). */
  readonly resultado = toSignal(
    toObservable(this.filtro).pipe(
      debounceTime(250),
      tap(() => { this.carregando.set(true); this.erro.set(null); }),
      switchMap(f => this.api.listar(f).pipe(catchError(e => {
        this.erro.set(mensagemDeErro(e, 'Não foi possível carregar as usinas.'));
        return of<Pagina<UsinaLista>>({ count: 0, next: null, previous: null, results: [] });
      }))),
      tap(() => this.carregando.set(false)),
    ),
    { initialValue: null },
  );

  readonly resumo = signal<ResumoUsinas | null>(null);

  readonly totalPaginas = computed(() => Math.max(1, Math.ceil((this.resultado()?.count ?? 0) / POR_PAGINA)));
  readonly intervalo = computed(() => {
    const total = this.resultado()?.count ?? 0;
    if (!total) return '0 de 0';
    const ini = (this.pagina() - 1) * POR_PAGINA + 1;
    return `${ini}–${Math.min(this.pagina() * POR_PAGINA, total)} de ${total}`;
  });
  readonly temFiltro = computed(() => !!(this.busca().trim() || this.status() || this.fabricante()));

  constructor() {
    // Permite chegar já filtrado, ex.: /usinas?status=alerta (links do dashboard)
    const st = inject(ActivatedRoute).snapshot.queryParamMap.get('status');
    if (st === 'online' || st === 'noite' || st === 'alerta' || st === 'offline') this.status.set(st);
    this.api.resumo().subscribe({ next: r => this.resumo.set(r), error: () => {} });
  }

  // ---------- Ações ----------
  definirBusca(v: string): void { this.busca.set(v); this.pagina.set(1); }
  definirStatus(s: StatusUsina | null): void { this.status.set(s); this.pagina.set(1); }
  alternarFabricante(f: string): void { this.fabricante.set(this.fabricante() === f ? null : f); this.pagina.set(1); }
  limparFiltros(): void { this.busca.set(''); this.status.set(null); this.fabricante.set(null); this.pagina.set(1); }

  ordenar(coluna: Coluna): void {
    const o = this.ordem();
    this.ordem.set({ coluna, asc: o.coluna === coluna ? !o.asc : true });
    this.pagina.set(1);
  }
  seta(coluna: Coluna): string {
    const o = this.ordem();
    return o.coluna === coluna ? (o.asc ? '↑' : '↓') : '';
  }
  irPara(p: number): void { this.pagina.set(Math.min(Math.max(1, p), this.totalPaginas())); }

  // ---------- Auxiliares ----------
  desempenho(u: UsinaLista): number | null {
    return u.esperado_mes_kwh > 0 ? (u.geracao_mes_kwh / u.esperado_mes_kwh) * 100 : null;
  }

  ultimaLeitura(iso: string | null): string {
    if (!iso) return 'sem leituras';
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
    if (min < 1) return 'agora';
    if (min < 60) return `há ${min} min`;
    if (min < 1440) return `há ${Math.floor(min / 60)} h`;
    return `há ${Math.floor(min / 1440)} d`;
  }
}
