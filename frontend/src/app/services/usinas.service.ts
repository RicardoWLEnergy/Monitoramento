import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export type StatusUsina = 'online' | 'alerta' | 'offline';
export type Plataforma = 'foxess' | 'huawei';

export const ROTULO_STATUS: Record<StatusUsina, string> = { online: 'Online', alerta: 'Alerta', offline: 'Offline' };
export const CLASSE_STATUS: Record<StatusUsina, string> = { online: 'ok', alerta: 'warn', offline: 'danger' };
export const PLATAFORMAS: { valor: Plataforma; rotulo: string }[] = [
  { valor: 'foxess', rotulo: 'FoxESS Cloud' },
  { valor: 'huawei', rotulo: 'Huawei FusionSolar' },
];

export interface Pagina<T> { count: number; next: string | null; previous: string | null; results: T[]; }

export interface UsinaLista {
  id: number;
  nome: string;
  plataforma: Plataforma;
  plataforma_nome: string;
  fabricante: string;
  fabricante_nome: string;
  cidade: string;
  uf: string;
  potencia_kwp: number;
  status: StatusUsina;
  ultima_leitura: string | null;
  potencia_atual_kw: number;
  geracao_hoje_kwh: number;
  geracao_mes_kwh: number;
  esperado_mes_kwh: number;
}

export interface ClienteVinculado { id: number; nome: string; email: string; }

export interface UsinaDetalhe extends UsinaLista {
  id_externo: string;
  endereco: string;
  latitude: number | null;
  longitude: number | null;
  link_maps: string | null;
  fuso_horario: string;
  alertas_ativos: boolean;
  limite_desempenho_pct: number;
  minutos_sem_comunicacao: number;
  clientes?: ClienteVinculado[];   // só vem para Admin/Colaborador
}

export interface ConfigAlertas {
  alertas_ativos: boolean;
  limite_desempenho_pct: number;
  minutos_sem_comunicacao: number;
}

export interface Inversor {
  id: number;
  numero_serie: string;
  modelo: string;
  potencia_nominal_kw: number;
  status: StatusUsina;
  potencia_atual_kw: number;
  geracao_hoje_kwh: number;
  ultima_leitura: string | null;
}

export interface PontoCurva { hora: string; kw: number; }
export interface Curva { data: string; fuso: string; pontos: PontoCurva[]; }

export interface MesGeracao {
  mes: string;          // 2026-11
  rotulo: string;       // nov/26
  gerado_kwh: number;
  esperado_kwh: number;
  parcial: boolean;     // mês em andamento
}

export interface GeracaoEsperada { mes: number; energia_kwh: number; }

export interface ResumoUsinas {
  total: number; potencia_kwp: number; online: number; alerta: number; offline: number;
}

/** O que já existe no banco para a usina. */
export interface CoberturaHistorico {
  energia_diaria: { inicio: string | null; fim: string | null; dias: number };
  curvas: { inicio: string | null; fim: string | null; dias: number };
  limite_curvas: string;   // dia mais antigo de curva que o banco guarda (retenção)
  inversores: number;
}

export interface ResultadoImportacao {
  dias_energia: number;
  dias_curva: number;
  leituras: number;
  falhas: string[];
  cobertura: CoberturaHistorico;
}

export interface FiltroUsinas {
  busca?: string;
  status?: StatusUsina | null;
  fabricante?: string | null;
  ordem?: string;
  page?: number;
}

/** Chamadas à API de usinas (/api/usinas/). */
@Injectable({ providedIn: 'root' })
export class UsinasService {
  private readonly http = inject(HttpClient);

  listar(filtro: FiltroUsinas): Observable<Pagina<UsinaLista>> {
    let params = new HttpParams();
    for (const [chave, valor] of Object.entries(filtro)) {
      if (valor !== null && valor !== undefined && valor !== '') params = params.set(chave, String(valor));
    }
    return this.http.get<Pagina<UsinaLista>>('/api/usinas/', { params });
  }

  resumo(): Observable<ResumoUsinas> {
    return this.http.get<ResumoUsinas>('/api/usinas/resumo/');
  }

  detalhe(id: number): Observable<UsinaDetalhe> {
    return this.http.get<UsinaDetalhe>(`/api/usinas/${id}/`);
  }

  inversores(id: number): Observable<Inversor[]> {
    return this.http.get<Inversor[]>(`/api/usinas/${id}/inversores/`);
  }

  curva(id: number, data?: string): Observable<Curva> {
    const params = data ? new HttpParams().set('data', data) : undefined;
    return this.http.get<Curva>(`/api/usinas/${id}/curva/`, { params });
  }

  geracaoMensal(id: number, meses = 12): Observable<MesGeracao[]> {
    return this.http.get<MesGeracao[]>(`/api/usinas/${id}/geracao-mensal/`, { params: { meses } });
  }

  geracaoEsperada(id: number): Observable<GeracaoEsperada[]> {
    return this.http.get<GeracaoEsperada[]>(`/api/usinas/${id}/geracao-esperada/`);
  }

  salvarGeracaoEsperada(id: number, valores: GeracaoEsperada[]): Observable<GeracaoEsperada[]> {
    return this.http.put<GeracaoEsperada[]>(`/api/usinas/${id}/geracao-esperada/`, valores);
  }

  salvarAlertas(id: number, config: ConfigAlertas): Observable<UsinaDetalhe> {
    return this.http.patch<UsinaDetalhe>(`/api/usinas/${id}/`, config);
  }

  coberturaHistorico(id: number): Observable<CoberturaHistorico> {
    return this.http.get<CoberturaHistorico>(`/api/usinas/${id}/historico/`);
  }

  /** Busca na plataforma a geração do período (pode levar alguns minutos). */
  importarHistorico(id: number, inicio: string, fim: string, curvas = true): Observable<ResultadoImportacao> {
    return this.http.post<ResultadoImportacao>(`/api/usinas/${id}/historico/`, { inicio, fim, curvas });
  }

  /** "Apaga" a usina: ela é desativada (some do sistema), mas o histórico fica no banco. Só Admin. */
  apagar(id: number): Observable<void> {
    return this.http.delete<void>(`/api/usinas/${id}/`);
  }

  definirClientes(id: number, clientes: number[]): Observable<UsinaDetalhe> {
    return this.http.put<UsinaDetalhe>(`/api/usinas/${id}/clientes/`, { clientes });
  }
}
