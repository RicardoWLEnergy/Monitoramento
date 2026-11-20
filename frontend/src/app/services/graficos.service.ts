import { Injectable, inject } from '@angular/core';
import * as echarts from 'echarts/core';
import type { EChartsCoreOption } from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
import { TemaService } from './tema.service';
import { diaMesBR } from './periodo';
import { ClimaDia, DiaGeracao, MesGeracao, PontoCurva, ROTULO_CLIMA } from './usinas.service';

// Só os módulos usados entram no pacote (tree-shaking)
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

/** Use nos componentes com gráfico: providers: [provideEchartsCore({ echarts })] */
export { echarts };

interface Cores {
  info: string;
  acento: string; referencia: string; texto: string; secundario: string; linha: string; superficie: string;
}

const AREA_ACENTO = 'rgba(239, 150, 0, 0.10)';

const SEMANA = ['dom', 'seg', 'ter', 'qua', 'qui', 'sex', 'sáb'];

/** Ícones do clima (desenhos Lucide: sun, cloud, cloud-rain) como imagem para o ECharts. */
const DESENHO_CLIMA = {
  ensolarado: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>',
  nublado: '<path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>',
  chuvoso: '<path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M16 14v6M8 14v6M12 16v6"/>',
};
const imagemClima = (desenho: string, cor: string) => 'data:image/svg+xml;utf8,' + encodeURIComponent(
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="${cor}" stroke-width="2" ` +
  `stroke-linecap="round" stroke-linejoin="round">${desenho}</svg>`);
/** "Chuvoso · 12 mm" (a chuva só aparece a partir de 1 mm). */
export const textoClima = (c: ClimaDia) =>
  (ROTULO_CLIMA[c.condicao] ?? '') + (c.chuva_mm >= 1 ? ` · ${numeroBR(c.chuva_mm, 0)} mm` : '');

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

  /**
   * Energia por dia de um período: uma barra por dia + linha do esperado do dia (esperado do mês ÷ dias do mês).
   * Hoje (em andamento) mais claro; dia sem dados fica vazio.
   */
  geracaoDiaria(dias: DiaGeracao[], hoje: string): EChartsCoreOption {
    const c = this.cores();
    const b = this.base(c);
    const temEsperado = dias.some(d => d.esperado_kwh);
    // Ícone do clima em cima das barras só em períodos curtos (em períodos longos fica só no texto do mouse)
    const comClima = dias.length <= 31 && dias.some(d => d.clima);
    const corClima = { ensolarado: c.acento, nublado: c.secundario, chuvoso: c.info };
    return {
      ...b.comum,
      grid: { ...b.comum.grid, top: comClima ? 60 : 44 },
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
          const d = dias[p[0].dataIndex];
          const semana = SEMANA[new Date(`${d.data}T12:00:00`).getDay()];
          const titulo = `<span style="color:${c.secundario}">${semana}, ${diaMesBR(d.data)}/${d.data.slice(0, 4)}` +
            `${d.data === hoje ? ' · em andamento' : ''}</span><br>`;
          let html = titulo + `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${c.acento};margin-right:6px"></span>` +
            (d.kwh === null ? 'Sem dados' : `Gerado <b>${numeroBR(d.kwh, 1)} kWh</b>`);
          if (d.esperado_kwh) {
            html += `<br><span style="display:inline-block;width:10px;height:2px;background:${c.referencia};margin:0 4px 3px 0"></span>` +
              `Esperado <b>${numeroBR(d.esperado_kwh, 1)} kWh</b>`;
            if (d.kwh !== null && d.data !== hoje) {
              html += `<br><span style="color:${c.secundario}">${numeroBR(d.kwh / d.esperado_kwh * 100)}% do esperado</span>`;
            }
          }
          if (d.clima) html += `<br><span style="color:${c.secundario}">Clima: ${textoClima(d.clima)}</span>`;
          return html;
        },
      },
      xAxis: { type: 'category', data: dias.map(d => diaMesBR(d.data)), ...b.eixoX },
      yAxis: this.eixoY(b, c, 'kWh'),
      series: [{
        name: 'Gerado', type: 'bar', barMaxWidth: 24, cursor: 'pointer',
        itemStyle: { color: c.acento, borderRadius: [4, 4, 0, 0] },
        label: comClima ? {
          show: true, position: 'top', distance: 4,
          formatter: (p: { dataIndex: number }) => {
            const clima = dias[p.dataIndex].clima;
            return clima ? `{${clima.condicao}|}` : '';
          },
          rich: Object.fromEntries((Object.keys(DESENHO_CLIMA) as (keyof typeof DESENHO_CLIMA)[]).map(k =>
            [k, { width: 14, height: 14, backgroundColor: { image: imagemClima(DESENHO_CLIMA[k], corClima[k]) } }])),
        } : undefined,
        data: dias.map(d => (d.data === hoje && d.kwh !== null ? { value: d.kwh, itemStyle: { opacity: 0.45 } } : d.kwh)),
        emphasis: { disabled: true },
      },
      ...(temEsperado ? [{
        name: 'Esperado', type: 'line', step: 'middle', data: dias.map(d => d.esperado_kwh),
        symbol: 'none', lineStyle: { width: 2, color: c.referencia }, itemStyle: { color: c.referencia },
        emphasis: { disabled: true },
      }] : [])],
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
              `Esperado${m.parcial ? ' no mês' : ''} <b>${numeroBR(m.esperado_kwh / div, casas)} ${unidade}</b>`;
            if (m.parcial) {
              // Mês em andamento: compara com o esperado até hoje, não com o mês inteiro
              html += `<br>Esperado até hoje <b>${numeroBR(m.esperado_ate_hoje_kwh / div, casas)} ${unidade}</b>`;
            }
            html += `<br><span style="color:${c.secundario}">${numeroBR(m.gerado_kwh / m.esperado_ate_hoje_kwh * 100)}% ` +
              `do esperado${m.parcial ? ' até hoje' : ''}</span>`;
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
      info: v('--info-txt'), acento: v('--wl-orange'), referencia: v('--muted'), texto: v('--txt'),
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
