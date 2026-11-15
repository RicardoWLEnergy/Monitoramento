import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

/** 'noite' = sem geração por falta de sol (normal, não é problema). */
export type StatusUsina = 'online' | 'noite' | 'alerta' | 'offline';
export type Plataforma = 'foxess' | 'huawei';

export const ROTULO_STATUS: Record<StatusUsina, string> = { online: 'Online', noite: 'Sem sol', alerta: 'Alerta', offline: 'Offline' };
export const CLASSE_STATUS: Record<StatusUsina, string> = { online: 'ok', noite: 'neutral', alerta: 'warn', offline: 'danger' };
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
  esperado_ate_hoje_kwh: number;   // esperado do mês proporcional aos dias já passados
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

/** Dados cadastrais que a equipe pode corrigir (vêm da plataforma só no primeiro cadastro). */
export interface DadosUsina {
  nome: string;
  endereco: string;
  cidade: string;
  uf: string;
  latitude: number | null;
  longitude: number | null;
  potencia_kwp: number;
  fuso_horario: string;
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

/** Energia de um dia (null = sem dados) e o esperado do dia (esperado do mês ÷ dias do mês; null = não cadastrado). */
export interface DiaGeracao { data: string; kwh: number | null; esperado_kwh: number | null; }
export interface GeracaoPeriodo { inicio: string; fim: string; dias: DiaGeracao[]; }

export interface MesGeracao {
  mes: string;          // 2026-11
  rotulo: string;       // nov/26
  gerado_kwh: number;
  esperado_kwh: number;            // do mês inteiro
  esperado_ate_hoje_kwh: number;   // mês atual: proporcional aos dias passados; meses fechados: = esperado_kwh
  parcial: boolean;     // mês em andamento
}

export interface GeracaoEsperada { mes: number; energia_kwh: number; }

export interface ResumoUsinas {
  total: number; potencia_kwp: number; online: number; noite: number; alerta: number; offline: number;
}

/** Importação de histórico pedida na tela (o servidor importa em segundo plano). */
export interface ImportacaoHistorico {
  id: number;
  inicio: string;
  fim: string;
  curvas: boolean;
  status: 'fila' | 'importando' | 'concluida' | 'erro';
  status_nome: string;
  etapa: 'energia' | 'curva';
  etapa_nome: string;
  passos_feitos: number;
  passos_total: number;
  dias_energia: number;
  dias_curva: number;
  leituras: number;
  falhas: string[];
  solicitado_por_nome: string | null;
  criado_em: string;
  iniciado_em: string | null;
  concluido_em: string | null;
}

/** O que já existe no banco para a usina + a importação mais recente. */
export interface CoberturaHistorico {
  energia_diaria: { inicio: string | null; fim: string | null; dias: number };
  curvas: { inicio: string | null; fim: string | null; dias: number };
  limite_curvas: string;   // dia mais antigo de curva que o banco guarda (retenção)
  inversores: number;
  importacao: ImportacaoHistorico | null;
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

  /** Energia de cada dia do período (até 1 ano). */
  geracaoDiaria(id: number, inicio: string, fim: string): Observable<GeracaoPeriodo> {
    return this.http.get<GeracaoPeriodo>(`/api/usinas/${id}/geracao-diaria/`, { params: { inicio, fim } });
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

  /** Admin e Colaborador. */
  salvarDados(id: number, dados: DadosUsina): Observable<UsinaDetalhe> {
    return this.http.patch<UsinaDetalhe>(`/api/usinas/${id}/`, dados);
  }

  /** Só Admin. */
  salvarAlertas(id: number, config: ConfigAlertas): Observable<UsinaDetalhe> {
    return this.http.patch<UsinaDetalhe>(`/api/usinas/${id}/`, config);
  }

  coberturaHistorico(id: number): Observable<CoberturaHistorico> {
    return this.http.get<CoberturaHistorico>(`/api/usinas/${id}/historico/`);
  }

  /** Pede a importação do período: o servidor importa em segundo plano (acompanhe pela cobertura). */
  importarHistorico(id: number, inicio: string, fim: string, curvas = true): Observable<CoberturaHistorico> {
    return this.http.post<CoberturaHistorico>(`/api/usinas/${id}/historico/`, { inicio, fim, curvas });
  }

  /** "Apaga" a usina: ela é desativada (some do sistema), mas o histórico fica no banco. Só Admin. */
  apagar(id: number): Observable<void> {
    return this.http.delete<void>(`/api/usinas/${id}/`);
  }

  definirClientes(id: number, clientes: number[]): Observable<UsinaDetalhe> {
    return this.http.put<UsinaDetalhe>(`/api/usinas/${id}/clientes/`, { clientes });
  }
}
