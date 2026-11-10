import { Injectable, inject } from '@angular/core';
import * as echarts from 'echarts/core';
import type { EChartsCoreOption } from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { TemaService } from './tema.service';
import { MesGeracao, PontoCurva } from './usinas.service';

// Só os módulos usados entram no pacote (tree-shaking)
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

/** Use nos componentes com gráfico: providers: [provideEchartsCore({ echarts })] */
export { echarts };

interface Cores {
  acento: string; referencia: string; texto: string; secundario: string; linha: string; superficie: string;
}

const AREA_ACENTO = 'rgba(239, 150, 0, 0.10)';

export const numeroBR = (v: number, casas = 0) =>
  v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });

/**
 * Opções dos gráficos ECharts com a identidade W.L Energy.
 * As cores vêm dos tokens CSS do tema atual; leia `tema.tema()` num computed
 * antes de chamar estes métodos para o gráfico se atualizar ao trocar o tema.
 */
@Injectable({ providedIn: 'root' })
export class GraficosService {
  private readonly tema = inject(TemaService);

  /** Curva de potência do dia — série única (sem legenda), área suave em laranja. */
  curvaPotencia(pontos: PontoCurva[]): EChartsCoreOption {
    const c = this.cores();
    const b = this.base(c);
    return {
      ...b.comum,
      tooltip: {
        ...b.tooltip, trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: c.secundario, width: 1 } },
        formatter: (p: { axisValue: string; value: number }[]) =>
          `<span style="color:${c.secundario}">${p[0].axisValue}</span><br><b>${numeroBR(p[0].value, 1)} kW</b>`,
      },
      xAxis: {
        type: 'category', boundaryGap: false, data: pontos.map(p => p.hora), ...b.eixoX,
        axisLabel: { ...b.eixoX.axisLabel, interval: (_: number, v: string) => v.endsWith(':00') && +v.slice(0, 2) % 2 === 0 },
      },
      yAxis: this.eixoY(b, c, 'kW'),
      series: [{
        name: 'Potência', type: 'line', data: pontos.map(p => p.kw),
        smooth: 0.3, symbol: 'none', showSymbol: false,
        lineStyle: { width: 2, color: c.acento, cap: 'round', join: 'round' },
        itemStyle: { color: c.acento }, areaStyle: { color: AREA_ACENTO }, emphasis: { disabled: true },
      }],
    };
  }

  /** Geração mensal: barras (gerado) + linha de referência (esperado). Mês atual mais claro. */
  geracaoMensal(meses: MesGeracao[], unidade: 'kWh' | 'MWh' = 'kWh'): EChartsCoreOption {
    const c = this.cores();
    const b = this.base(c);
    const div = unidade === 'MWh' ? 1000 : 1;
    const casas = unidade === 'MWh' ? 1 : 0;
    const temEsperado = meses.some(m => m.esperado_kwh > 0);
    return {
      ...b.comum,
      grid: { ...b.comum.grid, top: 44 },
      legend: {
        top: 0, right: 0, itemWidth: 14, itemHeight: 8, itemGap: 16,
        textStyle: { color: c.secundario, fontSize: 12, fontFamily: 'Inter' },
        data: [
          { name: 'Gerado', icon: 'roundRect' },
          ...(temEsperado ? [{ name: 'Esperado', icon: 'path://M0,4 L14,4 L14,6 L0,6 Z' }] : []),
        ],
      },
      tooltip: {
        ...b.tooltip, trigger: 'axis',
        axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(239,150,0,0.06)' } },
        formatter: (p: { dataIndex: number }[]) => {
          const m = meses[p[0].dataIndex];
          let html = `<span style="color:${c.secundario}">${m.rotulo}${m.parcial ? ' · em andamento' : ''}</span><br>` +
            `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${c.acento};margin-right:6px"></span>` +
            `Gerado <b>${numeroBR(m.gerado_kwh / div, casas)} ${unidade}</b>`;
          if (m.esperado_kwh > 0) {
            html += `<br><span style="display:inline-block;width:10px;height:2px;background:${c.referencia};margin:0 4px 3px 0"></span>` +
              `Esperado <b>${numeroBR(m.esperado_kwh / div, casas)} ${unidade}</b><br>` +
              `<span style="color:${c.secundario}">${numeroBR(m.gerado_kwh / m.esperado_kwh * 100)}% do esperado</span>`;
          }
          return html;
        },
      },
      xAxis: { type: 'category', data: meses.map(m => m.rotulo), ...b.eixoX },
      yAxis: this.eixoY(b, c, unidade),
      series: [
        {
          name: 'Gerado', type: 'bar', barMaxWidth: 24,
          itemStyle: { color: c.acento, borderRadius: [4, 4, 0, 0] },
          data: meses.map(m => {
            const v = +(m.gerado_kwh / div).toFixed(2);
            return m.parcial ? { value: v, itemStyle: { opacity: 0.45 } } : v;
          }),
          emphasis: { disabled: true },
        },
        ...(temEsperado ? [{
          name: 'Esperado', type: 'line', data: meses.map(m => +(m.esperado_kwh / div).toFixed(2)),
          symbol: 'none', lineStyle: { width: 2, color: c.referencia }, itemStyle: { color: c.referencia },
          emphasis: { disabled: true },
        }] : []),
      ],
    };
  }

  // ---------- base visual ----------
  private cores(): Cores {
    this.tema.tema();   // dependência explícita do tema
    const css = getComputedStyle(document.documentElement);
    const v = (n: string) => css.getPropertyValue(n).trim();
    return {
      acento: v('--wl-orange'), referencia: v('--muted'), texto: v('--txt'),
      secundario: v('--muted'), linha: v('--line'), superficie: v('--card'),
    };
  }

  private base(c: Cores) {
    const eixo = {
      axisLine: { lineStyle: { color: c.linha } },
      axisTick: { show: false },
      axisLabel: { color: c.secundario, fontSize: 11, fontFamily: 'Inter' },
      splitLine: { lineStyle: { color: c.linha, width: 1, type: 'solid' as const } },
    };
    return {
      comum: {
        textStyle: { fontFamily: 'Inter', color: c.texto },
        animationDuration: 300,
        grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      },
      tooltip: {
        backgroundColor: c.superficie, borderColor: c.linha, borderWidth: 1, padding: [8, 12],
        textStyle: { color: c.texto, fontSize: 12, fontFamily: 'Inter' },
        extraCssText: 'border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.12);',
      },
      eixoX: { ...eixo, splitLine: { show: false } },
      eixoY: eixo,
    };
  }

  private eixoY(b: ReturnType<GraficosService['base']>, c: Cores, unidade: string) {
    return {
      type: 'value', name: unidade, ...b.eixoY,
      nameTextStyle: { color: c.secundario, fontSize: 11, align: 'right' },
      axisLabel: { ...b.eixoY.axisLabel, formatter: (v: number) => numeroBR(v) },
    };
  }
}
