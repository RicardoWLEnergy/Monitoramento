import { DiaGeracao } from './usinas.service';

/** Data no formato AAAA-MM-DD no fuso local. */
export const isoLocal = (d: Date) => d.toLocaleDateString('sv-SE');
export const hojeIso = () => isoLocal(new Date());
export const diasAtras = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return isoLocal(d); };
/** '2026-11-05' -> '05/11' */
export const diaMesBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;

export interface AtalhoPeriodo { rotulo: string; inicio: string; fim: string; }

/** Atalhos do modo "Período" dos gráficos de geração (usina e Visão geral). O 2º (30 dias) é o padrão. */
export function atalhosPeriodo(): AtalhoPeriodo[] {
  const h = new Date();
  return [
    { rotulo: '7 dias', inicio: diasAtras(6), fim: hojeIso() },
    { rotulo: '30 dias', inicio: diasAtras(29), fim: hojeIso() },
    { rotulo: 'Este mês', inicio: isoLocal(new Date(h.getFullYear(), h.getMonth(), 1)), fim: hojeIso() },
    {
      rotulo: 'Mês anterior', inicio: isoLocal(new Date(h.getFullYear(), h.getMonth() - 1, 1)),
      fim: isoLocal(new Date(h.getFullYear(), h.getMonth(), 0)),
    },
  ];
}

export interface ResumoPeriodo {
  total: number; media: number; melhorDia: string; melhorKwh: number;
  esperado: number | null;      // soma do esperado dos dias com dados (null sem geração esperada cadastrada)
  desempenhoPct: number | null; // gerado × esperado, nos mesmos dias
}

/**
 * Total, média por dia, melhor dia e gerado × esperado. Conta só os dias COM dados
 * (um dia sem leitura não deve puxar o desempenho para baixo). null se o período não tem dados.
 */
export function resumoPeriodo(dias: DiaGeracao[]): ResumoPeriodo | null {
  const comDados = dias.filter(d => d.kwh !== null) as (DiaGeracao & { kwh: number })[];
  if (!comDados.length) return null;
  const total = comDados.reduce((t, d) => t + d.kwh, 0);
  const melhor = comDados.reduce((m, d) => (d.kwh > m.kwh ? d : m));
  const esperado = comDados.reduce((t, d) => t + (d.esperado_kwh ?? 0), 0) || null;
  return {
    total, media: total / comDados.length, melhorDia: diaMesBR(melhor.data), melhorKwh: melhor.kwh,
    esperado, desempenhoPct: esperado ? (total / esperado) * 100 : null,
  };
}
