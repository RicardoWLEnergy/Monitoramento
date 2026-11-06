/**
 * Dados SIMULADOS do detalhe de uma usina (curva do dia, histórico, inversores).
 * Gerados de forma determinística a partir do id, para não mudarem a cada recarga.
 */
import { Fabricante, StatusUsina, Usina } from './usinas.mock';

export interface PontoCurva { hora: string; kw: number; }
export interface MesHistorico { rotulo: string; geradoKwh: number; esperadoKwh: number; parcial: boolean; }
export interface Inversor {
  nome: string; modelo: string; serial: string;
  potenciaNominalKw: number; potenciaAtualKw: number; geracaoHojeKwh: number; status: StatusUsina;
}

/** Gerador pseudoaleatório simples com semente (mulberry32). */
function aleatorio(semente: number): () => number {
  let a = semente * 9973;
  return () => {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Potência a cada 5 min, das 05:30 às 18:30, escalada para bater com a geração do dia. */
export function curvaDoDia(u: Usina): PontoCurva[] {
  const rnd = aleatorio(u.id);
  const agora = new Date();
  const minAgora = agora.getHours() * 60 + agora.getMinutes();
  const inicio = 5 * 60 + 30, fim = 18 * 60 + 30, nascer = 6 * 60, por = 18 * 60;
  const ultimaLeitura = new Date(u.ultimaLeitura);
  const minLimite = Math.min(minAgora, ultimaLeitura.toDateString() === agora.toDateString()
    ? ultimaLeitura.getHours() * 60 + ultimaLeitura.getMinutes() : minAgora);

  const bruto: PontoCurva[] = [];
  for (let m = inicio; m <= fim && m <= minAgora; m += 5) {
    let kw = 0;
    if (m > nascer && m < por && m <= minLimite) {
      const x = (m - nascer) / (por - nascer);
      kw = Math.pow(Math.sin(Math.PI * x), 1.4);
      if (rnd() < 0.12) kw *= 0.45 + rnd() * 0.35;          // passagem de nuvem
      if (u.status === 'alerta' && m > 12 * 60) kw *= 0.6;   // queda de rendimento à tarde
    }
    bruto.push({ hora: `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`, kw });
  }

  const energia = bruto.reduce((t, p) => t + p.kw * (5 / 60), 0);
  const fator = energia > 0 ? u.geracaoHojeKwh / energia : 0;
  return bruto.map(p => ({ hora: p.hora, kw: +(p.kw * fator).toFixed(2) }));
}

/** Últimos 12 meses (o atual é parcial). */
export function historico12Meses(u: Usina): MesHistorico[] {
  const rnd = aleatorio(u.id + 100);
  // Sazonalidade aproximada de irradiação no DF (jan..dez)
  const sazonal = [0.93, 0.95, 0.96, 0.97, 1.0, 1.02, 1.08, 1.12, 1.06, 0.98, 0.92, 0.91];
  const meses = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];
  const hoje = new Date();
  const lista: MesHistorico[] = [];

  for (let i = 11; i >= 0; i--) {
    const d = new Date(hoje.getFullYear(), hoje.getMonth() - i, 1);
    const esperado = Math.round(u.esperadoMesKwh * sazonal[d.getMonth()]);
    const parcial = i === 0;
    const gerado = parcial ? u.geracaoMesKwh : Math.round(esperado * (0.88 + rnd() * 0.17));
    lista.push({
      rotulo: `${meses[d.getMonth()]}/${String(d.getFullYear()).slice(2)}`,
      geradoKwh: gerado, esperadoKwh: esperado, parcial,
    });
  }
  return lista;
}

const MODELOS: Record<Fabricante, string> = {
  WEG: 'SIW500H', FoxESS: 'Série T G3', Huawei: 'SUN2000',
};

export function inversores(u: Usina): Inversor[] {
  const rnd = aleatorio(u.id + 200);
  const qtd = Math.max(1, Math.ceil(u.potenciaKwp / 30));
  const nominal = +(u.potenciaKwp / qtd * 0.9).toFixed(1);
  return Array.from({ length: qtd }, (_, i) => {
    const comFalha = (u.status === 'offline') || (u.status === 'alerta' && i === qtd - 1);
    const status: StatusUsina = u.status === 'offline' ? 'offline' : comFalha ? 'alerta' : 'online';
    return {
      nome: `Inversor ${String(i + 1).padStart(2, '0')}`,
      modelo: `${u.fabricante} ${MODELOS[u.fabricante]}`,
      serial: `${u.fabricante.slice(0, 2).toUpperCase()}${Math.floor(rnd() * 9e8 + 1e8)}`,
      potenciaNominalKw: nominal,
      potenciaAtualKw: +(u.potenciaAtualKw / qtd * (comFalha && u.status === 'alerta' ? 0.4 : 1)).toFixed(1),
      geracaoHojeKwh: +(u.geracaoHojeKwh / qtd).toFixed(1),
      status,
    };
  });
}
