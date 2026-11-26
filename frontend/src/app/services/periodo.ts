import type { LucideIconData } from 'lucide-angular';

import { DiaGeracao, MesGeracao, PontoCurva } from './usinas.service';

/** Data no formato AAAA-MM-DD no fuso local. */
export const isoLocal = (d: Date) => d.toLocaleDateString('sv-SE');
export const hojeIso = () => isoLocal(new Date());
export const diasAtras = (n: number) => { const d = new Date(); d.setDate(d.getDate() - n); return isoLocal(d); };
/** '2026-11-05' -> '05/11' */
export const diaMesBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}`;
/** '2026-11-05' -> '05/11/2026' */
export const dataBR = (iso: string) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;

/** Dias entre duas datas AAAA-MM-DD (no fuso local, sem o deslocamento de UTC). */
export function diasEntre(de: string, ate: string): number {
  const local = (iso: string) => { const [a, m, d] = iso.split('-').map(Number); return new Date(a, m - 1, d).getTime(); };
  return Math.round((local(ate) - local(de)) / 86_400_000);
}

/** Escala do modo "Período": semana (seg a dom), mês, ano, ou intervalo livre. */
export type Escala = 'semana' | 'mes' | 'ano' | 'personalizado';
export const ESCALAS: { valor: Escala; rotulo: string }[] = [
  { valor: 'semana', rotulo: 'Semana' }, { valor: 'mes', rotulo: 'Mês' },
  { valor: 'ano', rotulo: 'Ano' }, { valor: 'personalizado', rotulo: 'Personalizado' },
];
const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro',
  'novembro', 'dezembro'];
const MESES_CURTOS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

const dataDe = (iso: string) => { const [a, m, d] = iso.split('-').map(Number); return new Date(a, m - 1, d); };

export interface Intervalo { inicio: string; fim: string; rotulo: string; }

/** O período da escala que contém a data de referência. Ex.: mês de 18/11/2026 → 01/11 a 30/11, "Novembro de 2026". */
export function intervaloDa(escala: Exclude<Escala, 'personalizado'>, referencia: string): Intervalo {
  const ref = dataDe(referencia);
  if (escala === 'ano') {
    return { inicio: `${ref.getFullYear()}-01-01`, fim: `${ref.getFullYear()}-12-31`, rotulo: `${ref.getFullYear()}` };
  }
  if (escala === 'mes') {
    const ini = new Date(ref.getFullYear(), ref.getMonth(), 1), fim = new Date(ref.getFullYear(), ref.getMonth() + 1, 0);
    const nome = MESES[ref.getMonth()];
    return { inicio: isoLocal(ini), fim: isoLocal(fim), rotulo: `${nome[0].toUpperCase()}${nome.slice(1)} de ${ref.getFullYear()}` };
  }
  // semana: segunda a domingo
  const seg = new Date(ref);
  seg.setDate(ref.getDate() - ((ref.getDay() + 6) % 7));
  const dom = new Date(seg);
  dom.setDate(seg.getDate() + 6);
  const parte = (d: Date, comMes: boolean, comAno: boolean) =>
    `${d.getDate()}${comMes ? ` de ${MESES_CURTOS[d.getMonth()]}.` : ''}${comAno ? ` de ${d.getFullYear()}` : ''}`;
  const mesmoAno = seg.getFullYear() === dom.getFullYear(), mesmoMes = mesmoAno && seg.getMonth() === dom.getMonth();
  return {
    inicio: isoLocal(seg), fim: isoLocal(dom),
    rotulo: `${parte(seg, !mesmoMes, !mesmoAno)} a ${parte(dom, true, true)}`,
  };
}

/** Avança (+1) ou volta (-1) uma semana, um mês ou um ano a partir da referência. */
export function deslocar(escala: Exclude<Escala, 'personalizado'>, referencia: string, passo: number): string {
  const ref = dataDe(intervaloDa(escala, referencia).inicio);
  if (escala === 'semana') ref.setDate(ref.getDate() + 7 * passo);
  else if (escala === 'mes') ref.setMonth(ref.getMonth() + passo);
  else ref.setFullYear(ref.getFullYear() + passo);
  return isoLocal(ref);
}

/** Ano em 12 barras: soma cada mês (gerado e esperado). Meses ainda por vir ficam zerados. */
export function agruparPorMes(dias: DiaGeracao[], ano: number, hoje: string): MesGeracao[] {
  return MESES_CURTOS.map((curto, i) => {
    const prefixo = `${ano}-${String(i + 1).padStart(2, '0')}`;
    const doMes = dias.filter(d => d.data.startsWith(prefixo));
    const gerado = doMes.reduce((t, d) => t + (d.kwh ?? 0), 0);
    const esperado = doMes.reduce((t, d) => t + (d.esperado_kwh ?? 0), 0);
    return {
      mes: prefixo, rotulo: `${curto}/${String(ano).slice(2)}`, gerado_kwh: gerado,
      esperado_kwh: esperado, esperado_ate_hoje_kwh: esperado, parcial: hoje.startsWith(prefixo),
    };
  });
}

export interface ResumoPeriodo {
  total: number; media: number; dias: number; melhorDia: string; melhorKwh: number;
  esperado: number | null;      // soma do esperado dos dias com dados (null sem geração esperada cadastrada)
  desempenhoPct: number | null; // gerado × esperado, nos mesmos dias (os que têm dados E esperado)
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
  const comEsperado = comDados.filter(d => d.esperado_kwh);
  const esperado = comEsperado.reduce((t, d) => t + (d.esperado_kwh ?? 0), 0) || null;
  const geradoComEsperado = comEsperado.reduce((t, d) => t + d.kwh, 0);
  return {
    total, media: total / comDados.length, dias: comDados.length, melhorDia: diaMesBR(melhor.data), melhorKwh: melhor.kwh,
    esperado, desempenhoPct: esperado ? (geradoComEsperado / esperado) * 100 : null,
  };
}

// ---------------------------------------------------------------------
// Cards de indicadores (os quatro do topo) quando não é o "hoje"
// ---------------------------------------------------------------------
const br = (v: number, casas = 0) => v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });
/** Energia legível: até 10.000 kWh em kWh; acima disso, em MWh. */
export const energiaBR = (kwh: number) =>
  kwh >= 10_000 ? `${br(kwh / 1000, 2)} MWh` : `${br(kwh, kwh < 100 ? 1 : 0)} kWh`;
export const pctBR = (pct: number | null) => (pct === null ? '—' : `${br(pct)}%`);

export interface CardKpi { rotulo: string; valor: string; detalhe: string; icone: LucideIconData; }

/** Gerado ÷ esperado × 100 (null sem esperado). */
export const pctDoEsperado = (kwh: number | null | undefined, esperado: number | null | undefined) =>
  esperado ? ((kwh ?? 0) / esperado) * 100 : null;

/** Maior potência da curva do dia e o horário. */
export function picoDaCurva(pontos: PontoCurva[]): PontoCurva | null {
  return pontos.length ? pontos.reduce((m, p) => (p.kw > m.kw ? p : m)) : null;
}

/** Os quatro cards do período: total, média por dia, gerado × esperado e melhor dia. */
export function cardsDoPeriodo(
  r: ResumoPeriodo | null, carregando: boolean,
  ic: { total: LucideIconData; media: LucideIconData; esperado: LucideIconData; melhor: LucideIconData },
): CardKpi[] {
  const vazio = carregando ? 'Carregando...' : 'sem geração neste período';
  return [
    { rotulo: 'Total no período', valor: r ? energiaBR(r.total) : '—',
      detalhe: r ? `${r.dias} ${r.dias === 1 ? 'dia' : 'dias'} com geração` : vazio, icone: ic.total },
    { rotulo: 'Média por dia', valor: r ? energiaBR(r.media) : '—', detalhe: r ? 'nos dias com geração' : vazio, icone: ic.media },
    { rotulo: 'Gerado × esperado', valor: pctBR(r?.desempenhoPct ?? null),
      detalhe: !r ? vazio : r.esperado === null ? 'sem geração esperada cadastrada' : `esperado: ${energiaBR(r.esperado)}`,
      icone: ic.esperado },
    { rotulo: 'Melhor dia', valor: r ? energiaBR(r.melhorKwh) : '—', detalhe: r ? r.melhorDia : vazio, icone: ic.melhor },
  ];
}

/** De quanto em quanto tempo as telas de acompanhamento se atualizam sozinhas (o ritmo da coleta). */
export const ATUALIZAR_A_CADA_MS = 5 * 60_000;
