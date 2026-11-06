import { Component, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ChartLine, ChevronLeft, ChevronRight, LucideAngularModule, Search, Settings } from 'lucide-angular';
import { Fabricante, StatusUsina, Usina } from '../../core/usinas.mock';
import { UsinasService } from '../../core/usinas.service';

type FiltroStatus = 'todas' | StatusUsina;
type Coluna = 'nome' | 'fabricante' | 'potenciaKwp' | 'potenciaAtualKw' | 'geracaoHojeKwh' | 'desempenho' | 'status';

const POR_PAGINA = 8;

/** Usinas: lista completa (busca, filtros, ordenação, paginação) com acesso à geração e às configurações. */
@Component({
  selector: 'app-usinas',
  imports: [DecimalPipe, RouterLink, LucideAngularModule],
  templateUrl: './usinas.component.html',
  styleUrl: './usinas.component.css',
})
export class UsinasComponent {
  private readonly usinas = inject(UsinasService).usinas;

  readonly icones = { ChartLine, ChevronLeft, ChevronRight, Search, Settings };

  // ---------- Estado da tabela ----------
  readonly busca = signal('');
  readonly filtroStatus = signal<FiltroStatus>('todas');
  readonly filtroFabricante = signal<Fabricante | null>(null);
  readonly ordem = signal<{ coluna: Coluna; asc: boolean }>({ coluna: 'status', asc: true });
  readonly pagina = signal(1);

  readonly fabricantes: Fabricante[] = ['WEG', 'FoxESS', 'Huawei'];
  readonly rotuloStatus: Record<StatusUsina, string> = { online: 'Online', alerta: 'Alerta', offline: 'Offline' };
  readonly classeStatus: Record<StatusUsina, string> = { online: 'ok', alerta: 'warn', offline: 'danger' };

  // ---------- Contagens (chips e título) ----------
  readonly contagem = computed(() => {
    const u = this.usinas();
    return {
      total: u.length,
      kwp: u.reduce((t, x) => t + x.potenciaKwp, 0),
      todas: u.length,
      online: u.filter(x => x.status === 'online').length,
      alerta: u.filter(x => x.status === 'alerta').length,
      offline: u.filter(x => x.status === 'offline').length,
    };
  });

  constructor() {
    // Permite chegar já filtrado, ex.: /usinas?status=alerta (links do dashboard)
    const st = inject(ActivatedRoute).snapshot.queryParamMap.get('status');
    if (st === 'online' || st === 'alerta' || st === 'offline') this.filtroStatus.set(st);
  }

  // ---------- Tabela ----------
  readonly filtradas = computed(() => {
    const termo = this.normalizar(this.busca());
    const st = this.filtroStatus();
    const fab = this.filtroFabricante();
    const { coluna, asc } = this.ordem();
    const pesoStatus: Record<StatusUsina, number> = { offline: 0, alerta: 1, online: 2 };

    const valor = (u: Usina): string | number => {
      if (coluna === 'desempenho') return this.desempenho(u);
      if (coluna === 'status') return pesoStatus[u.status];
      return u[coluna];
    };

    return this.usinas()
      .filter(u => st === 'todas' || u.status === st)
      .filter(u => !fab || u.fabricante === fab)
      .filter(u => !termo || this.normalizar(`${u.nome} ${u.cliente} ${u.cidade}`).includes(termo))
      .sort((a, b) => {
        const va = valor(a), vb = valor(b);
        const r = typeof va === 'string' ? va.localeCompare(vb as string, 'pt-BR') : va - (vb as number);
        return asc ? r : -r;
      });
  });

  readonly totalPaginas = computed(() => Math.max(1, Math.ceil(this.filtradas().length / POR_PAGINA)));
  readonly paginaAtual = computed(() => {
    const p = Math.min(this.pagina(), this.totalPaginas());
    return this.filtradas().slice((p - 1) * POR_PAGINA, p * POR_PAGINA);
  });
  readonly intervalo = computed(() => {
    const total = this.filtradas().length;
    if (!total) return '0 de 0';
    const p = Math.min(this.pagina(), this.totalPaginas());
    const ini = (p - 1) * POR_PAGINA + 1;
    return `${ini}–${Math.min(p * POR_PAGINA, total)} de ${total}`;
  });

  // ---------- Ações ----------
  definirBusca(v: string): void { this.busca.set(v); this.pagina.set(1); }
  definirStatus(s: FiltroStatus): void { this.filtroStatus.set(s); this.pagina.set(1); }
  alternarFabricante(f: Fabricante): void {
    this.filtroFabricante.set(this.filtroFabricante() === f ? null : f);
    this.pagina.set(1);
  }
  ordenar(coluna: Coluna): void {
    const o = this.ordem();
    this.ordem.set({ coluna, asc: o.coluna === coluna ? !o.asc : true });
  }
  seta(coluna: Coluna): string {
    const o = this.ordem();
    return o.coluna === coluna ? (o.asc ? '↑' : '↓') : '';
  }
  irPara(p: number): void { this.pagina.set(Math.min(Math.max(1, p), this.totalPaginas())); }

  // ---------- Auxiliares ----------
  desempenho(u: Usina): number { return (u.geracaoMesKwh / u.esperadoMesKwh) * 100; }

  ultimaLeitura(iso: string): string {
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
    if (min < 1) return 'agora';
    if (min < 60) return `há ${min} min`;
    if (min < 1440) return `há ${Math.floor(min / 60)} h`;
    return `há ${Math.floor(min / 1440)} d`;
  }

  private normalizar(s: string): string {
    return s.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().trim();
  }
}
