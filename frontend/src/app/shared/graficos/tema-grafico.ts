/**
 * Base visual dos gráficos ECharts, lida dos tokens CSS do tema atual.
 * Chame de novo quando o tema mudar (as cores vêm das variáveis do <html>).
 */
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import {
  DataZoomComponent, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

// Só os módulos usados entram no pacote (tree-shaking)
echarts.use([
  LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent,
  DataZoomComponent, MarkLineComponent, CanvasRenderer,
]);

export { echarts };

export interface CoresGrafico {
  acento: string; referencia: string; texto: string; secundario: string;
  linha: string; superficie: string; areaAcento: string;
}

export function coresDoTema(): CoresGrafico {
  const css = getComputedStyle(document.documentElement);
  const v = (n: string) => css.getPropertyValue(n).trim();
  return {
    acento: v('--wl-orange'),
    referencia: v('--muted'),
    texto: v('--txt'),
    secundario: v('--muted'),
    linha: v('--line'),
    superficie: v('--card'),
    areaAcento: 'rgba(239, 150, 0, 0.10)',
  };
}

export const numeroBR = (v: number, casas = 0) =>
  v.toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });

/** Opções comuns: fontes, grade discreta, tooltip no estilo dos cards. */
export function baseGrafico(c: CoresGrafico) {
  const eixo = {
    axisLine: { lineStyle: { color: c.linha } },
    axisTick: { show: false },
    axisLabel: { color: c.secundario, fontSize: 11, fontFamily: 'Inter' },
    splitLine: { lineStyle: { color: c.linha, width: 1, type: 'solid' as const } },
  };
  return {
    textStyle: { fontFamily: 'Inter', color: c.texto },
    animationDuration: 300,
    grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
    tooltip: {
      backgroundColor: c.superficie,
      borderColor: c.linha,
      borderWidth: 1,
      padding: [8, 12],
      textStyle: { color: c.texto, fontSize: 12, fontFamily: 'Inter' },
      extraCssText: 'border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.12);',
    },
    eixoX: { ...eixo, splitLine: { show: false } },
    eixoY: eixo,
  };
}
