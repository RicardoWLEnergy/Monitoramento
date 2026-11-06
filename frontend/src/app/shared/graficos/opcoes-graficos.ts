/**
 * Gráficos reutilizáveis (dashboard e detalhe da usina usam os mesmos).
 */
import type { EChartsCoreOption } from 'echarts/core';
import type { MesHistorico, PontoCurva } from '../../core/usina-detalhe.mock';
import { CoresGrafico, baseGrafico, numeroBR } from './tema-grafico';

/** Curva de potência do dia — série única (sem legenda), área suave em laranja. */
export function opcoesCurvaPotencia(pontos: PontoCurva[], c: CoresGrafico): EChartsCoreOption {
  const b = baseGrafico(c);
  return {
    textStyle: b.textStyle,
    animationDuration: b.animationDuration,
    grid: b.grid,
    tooltip: {
      ...b.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'line', lineStyle: { color: c.secundario, width: 1 } },
      formatter: (p: { axisValue: string; value: number }[]) =>
        `<span style="color:${c.secundario}">${p[0].axisValue}</span><br>` +
        `<b>${numeroBR(p[0].value, 1)} kW</b>`,
    },
    xAxis: {
      type: 'category', boundaryGap: false, data: pontos.map(p => p.hora), ...b.eixoX,
      axisLabel: {
        ...b.eixoX.axisLabel,
        interval: (_: number, v: string) => v.endsWith(':00') && +v.slice(0, 2) % 2 === 0,
      },
    },
    yAxis: {
      type: 'value', name: 'kW', ...b.eixoY,
      nameTextStyle: { color: c.secundario, fontSize: 11, align: 'right' },
      axisLabel: { ...b.eixoY.axisLabel, formatter: (v: number) => numeroBR(v) },
    },
    series: [{
      name: 'Potência', type: 'line', data: pontos.map(p => p.kw),
      smooth: 0.3, symbol: 'none', showSymbol: false,
      lineStyle: { width: 2, color: c.acento, cap: 'round', join: 'round' },
      itemStyle: { color: c.acento },
      areaStyle: { color: c.areaAcento },
      emphasis: { disabled: true },
    }],
  };
}

/** Geração mensal: barras (gerado) + linha de referência (esperado). Mês atual mais claro. */
export function opcoesGeracaoMensal(meses: MesHistorico[], c: CoresGrafico, unidade: 'kWh' | 'MWh' = 'kWh'): EChartsCoreOption {
  const b = baseGrafico(c);
  const div = unidade === 'MWh' ? 1000 : 1;
  const casas = unidade === 'MWh' ? 1 : 0;
  return {
    textStyle: b.textStyle,
    animationDuration: b.animationDuration,
    grid: { ...b.grid, top: 44 },
    legend: {
      top: 0, right: 0, itemWidth: 14, itemHeight: 8, itemGap: 16,
      textStyle: { color: c.secundario, fontSize: 12, fontFamily: 'Inter' },
      data: [
        { name: 'Gerado', icon: 'roundRect' },
        { name: 'Esperado', icon: 'path://M0,4 L14,4 L14,6 L0,6 Z' },
      ],
    },
    tooltip: {
      ...b.tooltip,
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(239,150,0,0.06)' } },
      formatter: (p: { dataIndex: number }[]) => {
        const m = meses[p[0].dataIndex];
        const pct = (m.geradoKwh / m.esperadoKwh) * 100;
        return `<span style="color:${c.secundario}">${m.rotulo}${m.parcial ? ' · em andamento' : ''}</span><br>` +
          `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${c.acento};margin-right:6px"></span>` +
          `Gerado <b>${numeroBR(m.geradoKwh / div, casas)} ${unidade}</b><br>` +
          `<span style="display:inline-block;width:10px;height:2px;background:${c.referencia};margin:0 4px 3px 0"></span>` +
          `Esperado <b>${numeroBR(m.esperadoKwh / div, casas)} ${unidade}</b><br>` +
          `<span style="color:${c.secundario}">${numeroBR(pct)}% do esperado</span>`;
      },
    },
    xAxis: { type: 'category', data: meses.map(m => m.rotulo), ...b.eixoX },
    yAxis: {
      type: 'value', name: unidade, ...b.eixoY,
      nameTextStyle: { color: c.secundario, fontSize: 11, align: 'right' },
      axisLabel: { ...b.eixoY.axisLabel, formatter: (v: number) => numeroBR(v) },
    },
    series: [
      {
        name: 'Gerado', type: 'bar', barMaxWidth: 24,
        itemStyle: { color: c.acento, borderRadius: [4, 4, 0, 0] },
        data: meses.map(m => {
          const v = +(m.geradoKwh / div).toFixed(2);
          return m.parcial ? { value: v, itemStyle: { opacity: 0.45 } } : v;
        }),
        emphasis: { disabled: true },
      },
      {
        name: 'Esperado', type: 'line', data: meses.map(m => +(m.esperadoKwh / div).toFixed(2)),
        symbol: 'none',
        lineStyle: { width: 2, color: c.referencia },
        itemStyle: { color: c.referencia },
        emphasis: { disabled: true },
      },
    ],
  };
}
