import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { MesGeracao, PontoCurva, StatusUsina } from './usinas.service';

export interface Dashboard {
  kpis: {
    geracao_hoje_kwh: number;
    potencia_atual_kw: number;
    geracao_mes_kwh: number;
    esperado_mes_kwh: number;
    desempenho_mes_pct: number | null;   // null quando não há geração esperada cadastrada
    potencia_instalada_kwp: number;
    total: number;
    online: number;
    alerta: number;
    noite: number;
    offline: number;
  };
  atencao: { id: number; nome: string; status: StatusUsina; ultima_leitura: string | null; motivo: string }[];
  menor_desempenho: { id: number; nome: string; pct: number }[];
  curva_hoje: PontoCurva[];
  geracao_mensal: MesGeracao[];
}

/** Dados da Visão geral (/api/dashboard/), já filtrados pelo perfil do usuário. */
@Injectable({ providedIn: 'root' })
export class DashboardService {
  private readonly http = inject(HttpClient);

  carregar(): Observable<Dashboard> {
    return this.http.get<Dashboard>('/api/dashboard/');
  }
}
