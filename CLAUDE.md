# W.L Energy — Identidade Visual (CLAUDE.md portátil)

> Copie este arquivo para a raiz de qualquer projeto da W.L Energy (ou cole o
> conteúdo no `CLAUDE.md` existente). Ele define **como toda interface, página,
> PDF ou documento da empresa deve parecer**. Siga estas regras sempre que criar
> ou alterar telas, componentes, e-mails, relatórios e apresentações.

---

## 1. Essência da marca

- Empresa de energia solar fotovoltaica de Brasília–DF (+ O&M, Mercado Livre de
  Energia e Mobilidade Elétrica).
- Leitura visual: **técnica, confiante e premium**. Essência: *Energética ·
  Confiável · Moderna*.
- Base **quase monocromática (preto e branco)** com **um único acento: o laranja
  ENERGY `#EF9600`**.
- Forma característica: **canto chanfrado ("tab")**, herdado do selo ENERGY do
  logo — não cantos arredondados grandes.
- **Proibido emoji** em qualquer interface, PDF ou texto da marca. O único
  "ícone" de texto permitido é a seta `→`.

---

## 2. Paleta de cores

### 2.1 Cores oficiais (fonte: paleta da marca, com Pantone)

| Papel | Nome | HEX | Pantone | Token |
|---|---|---|---|---|
| **Acento principal** | ENERGY Orange | `#EF9600` | 2012 C | `--wl-orange` |
| Base escura | Black | `#000000` | — | `--wl-black` |
| Base clara | White | `#FFFFFF` | — | `--wl-white` |
| Painel claro | Light Gray | `#F2F2F2` | 1 C | `--wl-gray-100` |
| Sub-marca O&M | Azul O&M | `#003DA5` | 293 C | `--wl-om` |
| Sub-marca Mercado Livre | Lima | `#C0DF16` | 2297 C | `--wl-livre` |
| Sub-marca Mobility | Cinza | `#A7A8A9` | Cool Gray 6 C | `--wl-mobility` |

### 2.2 Variações do laranja

| Uso | HEX | Token |
|---|---|---|
| Hover (fica mais claro) | `#FFAB1F` | `--accent-hover` |
| Pressionado / texto de alerta no claro | `#C97C00` | `--wl-orange-dark` |
| Laranja suave (texto de alerta no escuro) | `#F7C266` | `--wl-orange-light` |
| Fundo de linha em hover | `rgba(239,150,0,0.05)` (claro) / `0.07` (escuro) | `--row-hover` |
| Item selecionado | `rgba(239,150,0,0.16)` | — |
| Brilho do botão principal | `0 4px 14px rgba(239,150,0,0.28)` | — |

### 2.3 Escala de cinzas

| Token | HEX | Uso |
|---|---|---|
| `--wl-gray-100` | `#F2F2F2` | fundo de página (tema claro), painéis invertidos |
| `--wl-gray-200` | `#E6E6E6` | bordas de cards no claro, hover em sólidos brancos |
| `--wl-gray-300` | `#D9D9D9` | linhas finas (hairline) no claro, borda de input |
| `--wl-gray-500` | `#A7A8A9` | texto apagado no escuro, labels da sidebar |
| `--wl-gray-700` | `#4D4D4D` | texto secundário no claro |
| `--wl-gray-900` | `#1A1A1A` | cards sobre preto, item ativo da sidebar |

### 2.4 Status / semânticas

| Estado | Claro (texto / fundo) | Escuro (texto / fundo) |
|---|---|---|
| Sucesso / fechado | `#1F7A33` / `#E3F0E5` | `#6FDD8B` ou lima `#C0DF16` / `rgba(52,199,108,.16)` |
| Info / enviado | `#2F5FC4` (ou `#003DA5`) / `#E3ECFA` | `#8FB4EE` / `rgba(74,127,212,.18)` |
| Alerta | `#C97C00` / `#FDEACC` | `#F7C266` / `rgba(239,150,0,.14)` |
| Erro / perdido | `#E23B2E` / `#FADEDB` | `#FF6A5E` / `rgba(226,59,46,.16)` |
| Rascunho / neutro | `#4D4D4D` / `#E6E6E6` | `#A7A8A9` / `rgba(255,255,255,.12)` |

### 2.5 Regras de uso das cores

- O **laranja é escasso de propósito**: botão principal, link, item ativo do
  menu, filete de destaque, palavra-chave de um título, valor principal (preço),
  foco de input, spinner. Nunca pintar áreas grandes de laranja.
- **Texto sobre laranja é sempre preto** (`#000`), nunca branco.
- Cada vertical tem a sua cor de "tab", mas o laranja ENERGY domina o produto
  principal: **O&M → azul `#003DA5` (texto branco)**, **Mercado Livre → lima
  `#C0DF16` (texto preto)**, **Mobility → cinza `#A7A8A9` (texto preto)**.
- **Sem gradientes decorativos.** A única exceção é o escurecimento sobre fotos
  (`linear-gradient(180deg, rgba(0,0,0,0) 30%, rgba(0,0,0,.55) 100%)`).
- Fundos são **lisos** (preto ou cinza-claro) — sem texturas nem padrões.

---

## 3. Temas

### Marketing / site / PDFs de apresentação → **escuro por padrão**
Fundo `#000`, texto `#FFF`, cards `#1A1A1A`, bordas `rgba(255,255,255,.12)`.

### Software interno (sistemas, painéis) → **sidebar preta fixa + conteúdo claro ou escuro**
- **Sidebar sempre preta** nos dois temas; item ativo com **barra laranja de 3px
  à esquerda**.
- **Tema claro (padrão):** fundo `#F2F2F2`, cards `#FFFFFF`, texto `#000`,
  secundário `#4D4D4D`, bordas `#E6E6E6`.
- **Tema escuro:** fundo `#0D0D0D`, cards `#1A1A1A`, texto `#FFF`, secundário
  `#A7A8A9`, bordas `rgba(255,255,255,.10)`, inputs `#000`.
- Tema escolhido por pessoa, salvo em `localStorage` e aplicado em
  `<html data-theme="...">` por script inline no `<head>` **antes** do CSS (sem
  piscar).
- **Login sempre escuro**, sem sidebar, card `#1A1A1A` centralizado sobre `#000`.
- **Nunca** escrever cor clara fixa (`#fff`, `#f2f2f2`) em tela nova: use as
  variáveis semânticas, senão o tema escuro quebra.

---

## 4. Tipografia

| Papel | Fonte | Peso |
|---|---|---|
| Títulos, números, KPIs, preços | **Space Grotesk** (`--font-display`) | 700 em sistemas; 300 (Light) em títulos grandes de marketing |
| Corpo de texto em sistemas | **Inter** (`--font-sans`) | 400 / 500 / 600 |
| Corpo de texto em marketing/PDF | Space Grotesk | 400 |

- Fontes: Space Grotesk (Google Fonts, pesos 300–700) e Inter Variable.
  Fallback: `"Helvetica Neue", Arial, sans-serif`.
- **Títulos grandes de marketing:** Light 300, tracking `-0.02em`, entrelinha
  `1.05`, quebrando em 2–3 linhas.
- **H1 de sistema:** 26px, 700, `-0.02em`, Space Grotesk.
- **Labels, eyebrows e cabeçalhos de tabela:** MAIÚSCULAS, peso 500–600,
  tamanho 10.5–12px, **tracking `0.14em`**, cor secundária.
- Números: `font-variant-numeric: tabular-nums`; formato pt-BR
  (`R$ 90.776,35`, `65,28 kWp`).
- Escala: 11 · 12 · 14 · 16 · 18 · 20 · 24 · 30 · 40 · 56 · 72px.
- Títulos em *sentence case*; MAIÚSCULAS só em labels/tags pequenas.

---

## 5. Forma, espaçamento e elevação

- **Grid de 4px:** 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64 · 96 · 128.
- **Raios pequenos:** 4–6px (inputs, botões pequenos), 8px (cards, botões,
  modais), 12px no máximo. Pílula `999px` só para tags/chips.
- **Canto chanfrado da marca** (corta o canto inferior esquerdo em 14px):
  ```css
  --clip-tab: polygon(0 0, 100% 0, 100% 100%, 14px 100%, 0 calc(100% - 14px));
  ```
  Use em: selos/badges, caixa de preço de destaque, callouts, CTAs de
  marketing. (Em sistemas internos o botão principal **não** usa chanfro.)
- **Bordas:** 1px finas; divisor horizontal de linha fina; filete laranja de
  largura total sob títulos é recurso recorrente.
- **Sombras:** raras e sutis.
  - `--shadow-sm: 0 1px 2px rgba(0,0,0,.08)`
  - `--shadow-md: 0 8px 24px rgba(0,0,0,.12)` (no escuro: `.5`)
  - `--shadow-accent: 0 8px 28px rgba(239,150,0,.32)` — só no CTA mais importante.
- **Movimento:** 120–200ms, `cubic-bezier(0.22, 0.61, 0.36, 1)`, sem bounce.
  Clique "afunda" 1px (`translateY(1px)`).

---

## 6. Componentes padrão

| Componente | Visual |
|---|---|
| **Botão primário** | fundo `#EF9600`, texto preto 600, raio 8px, brilho laranja suave; hover `#FFAB1F`; pressionado `#C97C00` |
| **Botão secundário** | fundo do card, borda fina; hover = borda e texto laranjas |
| **Card** | fundo `--card`, borda 1px `--line`, raio 8px, padding 20px |
| **KPI** | card com **filete laranja de 3px à esquerda**, label MAIÚSCULA pequena, número grande bold em Space Grotesk |
| **Caixa de preço** | fundo preto, chanfro `--clip-tab`, valor em laranja 30px bold |
| **Tabela** | cabeçalho **suave** (cinza `#F6F6F7` / `#222` no escuro, nunca preto), MAIÚSCULAS 10.5px tracking .14em; hover da linha em laranja translúcido; números à direita |
| **Tag de status** | pílula (`999px`), 11px 600, cores da tabela 2.4 |
| **Chip de filtro** | pílula com borda; ativo = fundo laranja + texto preto |
| **Abas** | texto 600 cinza; aba ativa com sublinhado laranja de 2px |
| **Input** | raio 6px, borda `#D9D9D9`; foco = contorno laranja 2px |
| **Checkbox/radio** | `accent-color: #EF9600` |
| **Alerta** | fundo suave + **borda esquerda de 3px** (vermelho erro / laranja aviso) |
| **Avatar** | círculo laranja com iniciais em preto 700 |
| **Loading** | spinner circular com topo laranja + "Carregando..." em Space Grotesk |
| **Topo mobile** | barra preta com **borda inferior laranja de 2px** |
| **Estado vazio** | borda tracejada, texto centralizado cinza, link laranja |

Toda tabela de dados deve ter: busca + filtros em chips + ordenação pelo
cabeçalho (seta `↑`/`↓` laranja) + paginação.

---

## 7. Ícones, logo e imagens

- Marca é **pobre em ícones** de propósito. Quando um ícone funcional for
  necessário, usar **Lucide** (traço fino ~1.7, geométrico), monocromático
  (`currentColor` ou laranja).
- Logos disponíveis: `wl-energy-white.png` (para fundo escuro),
  `wl-energy-allblack.png` (fundo claro), `wl-mark-white.png` /
  `wl-mark-black.png` (só o monograma WL). Manter área de respiro e o **®** em
  aplicações formais.
- **Fotografia real** (equipes com EPI, usinas, pôr do sol dourado), tom quente,
  nunca ilustração. Blocos de foto em largura total ou metade foto / metade
  painel liso.

---

## 8. Texto e tom de voz

- Português do Brasil, com acentos; moeda `R$`; vírgula decimal.
- Direto, confiante, focado em benefício — nunca apelativo nem engraçadinho.
- **Prova antes de adjetivo:** números concretos ("até 90% da sua conta de luz",
  "65,28 kWp · 128 módulos de 510Wp").
- CTAs curtos e ativos: *Solicitar orçamento*, *Simular economia*,
  *Ver projetos* — opcionalmente com `→`.
- Nome: **WL** no texto corrido, **W.L Energy** no formal.

---

## 9. Tokens prontos (cole no CSS do novo projeto)

```css
@import url("https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Inter:wght@400;500;600;700&display=swap");

:root {
  color-scheme: light;

  /* Paleta oficial */
  --wl-black: #000000;
  --wl-white: #ffffff;
  --wl-gray-100: #f2f2f2;
  --wl-gray-200: #e6e6e6;
  --wl-gray-300: #d9d9d9;
  --wl-gray-500: #a7a8a9;
  --wl-gray-700: #4d4d4d;
  --wl-gray-900: #1a1a1a;
  --wl-orange: #ef9600;
  --wl-orange-light: #f7c266;
  --wl-orange-dark: #c97c00;
  --wl-om: #003da5;
  --wl-livre: #c0df16;
  --wl-mobility: #a7a8a9;
  --wl-danger: #e23b2e;

  /* Acento */
  --accent: var(--wl-orange);
  --accent-hover: #ffab1f;
  --accent-pressed: var(--wl-orange-dark);
  --accent-contrast: #000000;

  /* Tipografia */
  --font-sans: "Inter", "Helvetica Neue", Arial, sans-serif;
  --font-display: "Space Grotesk", "Helvetica Neue", Arial, sans-serif;
  --tracking-tight: -0.02em;
  --tracking-wider: 0.14em;

  /* Forma */
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --clip-tab: polygon(0 0, 100% 0, 100% 100%, 14px 100%, 0 calc(100% - 14px));

  /* Efeitos */
  --ease-out: cubic-bezier(0.22, 0.61, 0.36, 1);
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.08);
  --shadow-md: 0 8px 24px rgba(0, 0, 0, 0.12);
  --shadow-accent: 0 8px 28px rgba(239, 150, 0, 0.32);

  /* Sidebar (preta nos dois temas) */
  --sb-bg: var(--wl-black);
  --sb-txt: rgba(255, 255, 255, 0.72);
  --sb-label: var(--wl-gray-500);
  --sb-line: rgba(255, 255, 255, 0.12);
  --sb-active-bg: var(--wl-gray-900);
  --sb-active-txt: #ffffff;

  /* Tema CLARO (padrão) */
  --bg: var(--wl-gray-100);
  --card: var(--wl-white);
  --line: var(--wl-gray-200);
  --hairline: var(--wl-gray-300);
  --txt: var(--wl-black);
  --muted: var(--wl-gray-700);
  --input-bg: #ffffff;
  --th-bg: #f6f6f7;
  --th-txt: var(--wl-gray-700);
  --row-hover: rgba(239, 150, 0, 0.05);
  --kpi-bg: var(--wl-gray-100);
  --ok: #1f7a33;          --ok-bg: #e3f0e5;
  --info-txt: #2f5fc4;    --info-bg: #e3ecfa;
  --warn-txt: var(--wl-orange-dark); --warn-bg: #fdeacc;
  --danger-txt: var(--wl-danger);    --danger-bg: #fadedb;
}

/* Tema ESCURO */
html[data-theme="escuro"] {
  color-scheme: dark;
  --sb-active-bg: rgba(239, 150, 0, 0.14);
  --sb-active-txt: var(--wl-orange);
  --bg: #0d0d0d;
  --card: var(--wl-gray-900);
  --line: rgba(255, 255, 255, 0.10);
  --hairline: rgba(255, 255, 255, 0.18);
  --txt: #ffffff;
  --muted: var(--wl-gray-500);
  --input-bg: #000000;
  --th-bg: #222222;
  --th-txt: rgba(255, 255, 255, 0.66);
  --row-hover: rgba(239, 150, 0, 0.07);
  --kpi-bg: #262626;
  --ok: #6fdd8b;          --ok-bg: rgba(52, 199, 108, 0.16);
  --info-txt: #8fb4ee;    --info-bg: rgba(74, 127, 212, 0.18);
  --warn-txt: var(--wl-orange-light); --warn-bg: rgba(239, 150, 0, 0.14);
  --danger-txt: #ff6a5e;  --danger-bg: rgba(226, 59, 46, 0.16);
  --shadow-md: 0 8px 24px rgba(0, 0, 0, 0.5);
}

body { margin: 0; font-family: var(--font-sans); background: var(--bg); color: var(--txt); }
h1, h3, h4 { font-family: var(--font-display); letter-spacing: var(--tracking-tight); }
::selection { background: var(--wl-orange); color: var(--wl-black); }
:focus-visible { outline: 2px solid var(--wl-orange); outline-offset: 2px; }

.eyebrow, .label { font-size: 10.5px; font-weight: 600; text-transform: uppercase;
  letter-spacing: var(--tracking-wider); color: var(--muted); }

.btn { display: inline-flex; align-items: center; gap: 8px; padding: 9px 18px;
  border-radius: var(--radius-md); border: 1px solid var(--hairline);
  background: var(--card); color: var(--txt); font: 500 13px var(--font-sans);
  cursor: pointer; transition: all 120ms var(--ease-out); }
.btn:hover { border-color: var(--wl-orange); color: var(--wl-orange); }
.btn:active { transform: translateY(1px); }
.btn.primary { background: var(--accent); border: none; color: var(--wl-black);
  font-weight: 600; box-shadow: 0 4px 14px rgba(239, 150, 0, 0.28); }
.btn.primary:hover { background: var(--accent-hover); color: var(--wl-black); }
.btn.primary:active { background: var(--accent-pressed); box-shadow: none; }

.card { background: var(--card); border: 1px solid var(--line);
  border-radius: var(--radius-md); padding: 20px; }

.kpi { position: relative; overflow: hidden; background: var(--card);
  border: 1px solid var(--line); border-radius: var(--radius-md); padding: 13px 14px 13px 16px; }
.kpi::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0;
  width: 3px; background: var(--wl-orange); }
.kpi strong { font: 700 21px var(--font-display); font-variant-numeric: tabular-nums; }

.tag { padding: 3px 11px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.tab-chamfer { clip-path: var(--clip-tab); }
```

---

## 10. Checklist antes de entregar uma tela

- [ ] Só uma cor de acento (laranja `#EF9600`), usada com moderação.
- [ ] Texto sobre laranja em preto.
- [ ] Títulos/números em Space Grotesk; corpo em Inter (sistemas).
- [ ] Labels em MAIÚSCULAS com tracking `0.14em`.
- [ ] Raios pequenos (≤12px); chanfro `--clip-tab` onde houver destaque de marca.
- [ ] Funciona nos temas claro **e** escuro (só variáveis, nenhuma cor fixa clara).
- [ ] Nenhum emoji; no máximo a seta `→`.
- [ ] Números e moeda no formato pt-BR.
