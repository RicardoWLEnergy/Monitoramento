import { Injectable, computed, signal } from '@angular/core';
import { Usina, USINAS_MOCK } from './usinas.mock';
import { MesHistorico, PontoCurva, curvaDoDia, historico12Meses } from './usina-detalhe.mock';

/** Configurações de monitoramento por usina (limites de alerta e integração). */
export interface ConfigUsina {
  idPlataforma: string;          // id da usina no portal do fabricante
  limiteDesempenhoPct: number;   // alerta se gerar abaixo de X% do esperado
  minutosSemComunicacao: number; // alerta de offline após X minutos sem leitura
  alertasAtivos: boolean;
}

/**
 * Fonte única dos dados de usinas para as telas.
 * Hoje lê do mock em memória; depois passará a chamar a API Django
 * sem que as telas precisem mudar.
 */
@Injectable({ providedIn: 'root' })
export class UsinasService {
  private readonly _usinas = signal<Usina[]>(USINAS_MOCK.map(u => ({ ...u })));
  private readonly _configs = signal<Record<number, ConfigUsina>>(
    Object.fromEntries(USINAS_MOCK.map(u => [u.id, {
      idPlataforma: `${u.fabricante.toUpperCase()}-${String(100000 + u.id * 7919).slice(0, 6)}`,
      limiteDesempenhoPct: 85,
      minutosSemComunicacao: 60,
      alertasAtivos: true,
    }])),
  );

  readonly usinas = this._usinas.asReadonly();

  porId(id: number): Usina | null {
    return this._usinas().find(u => u.id === id) ?? null;
  }

  config(id: number): ConfigUsina | null {
    return this._configs()[id] ?? null;
  }

  /** Salva dados cadastrais + configurações (simulado, só em memória). */
  async salvar(id: number, dados: Partial<Usina>, config: ConfigUsina): Promise<void> {
    await new Promise(r => setTimeout(r, 400));
    this._usinas.update(lista => lista.map(u => (u.id === id ? { ...u, ...dados } : u)));
    this._configs.update(c => ({ ...c, [id]: { ...config } }));
  }

  /** Curva de potência somada de todas as usinas (carteira). */
  readonly curvaCarteira = computed<PontoCurva[]>(() => {
    const soma = new Map<string, number>();
    for (const u of this._usinas()) {
      for (const p of curvaDoDia(u)) soma.set(p.hora, (soma.get(p.hora) ?? 0) + p.kw);
    }
    return [...soma.entries()].map(([hora, kw]) => ({ hora, kw: +kw.toFixed(2) }));
  });

  /** Histórico de 12 meses somado de todas as usinas (carteira). */
  readonly historicoCarteira = computed<MesHistorico[]>(() => {
    const listas = this._usinas().map(historico12Meses);
    if (!listas.length) return [];
    return listas[0].map((m, i) => ({
      rotulo: m.rotulo,
      parcial: m.parcial,
      geradoKwh: listas.reduce((t, l) => t + l[i].geradoKwh, 0),
      esperadoKwh: listas.reduce((t, l) => t + l[i].esperadoKwh, 0),
    }));
  });
}
