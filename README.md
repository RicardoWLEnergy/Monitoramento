# Monitoramento · W.L Energy

Sistema de monitoramento das usinas fotovoltaicas da W.L Energy. Ele coleta a geração diretamente
das plataformas dos fabricantes (**FoxESS Cloud** — inclui os inversores WEG — e **Huawei FusionSolar**)
e mostra tudo em um painel web com acesso por perfil.

| Camada | Tecnologia |
|---|---|
| Backend (API) | Django 5.2 + Django REST Framework + login JWT |
| Banco de dados | PostgreSQL 17 |
| Frontend (telas) | Angular 19 + ECharts (gráficos) + Lucide (ícones) |
| Coleta | comando `coletar` (tempo real a cada 5 min + rotina diária) |

---

## Perfis de acesso

| Perfil | O que pode fazer |
|---|---|
| **Admin** | tudo: usuários, alertas, geração esperada, apagar usinas |
| **Colaborador** | vê todas as usinas, cadastra clientes, vincula usinas pela SN, importa histórico |
| **Cliente** | vê só as usinas vinculadas a ele |

As regras ficam em um só lugar: `backend/usuarios/permissoes.py`.

## Como uma usina entra no sistema

Só entra no banco o que for cadastrado. Em **Clientes → Novo cliente**, informe os dados do cliente,
a **plataforma** e a **SN de um inversor**. O sistema busca a usina daquela SN na plataforma, grava a
usina inteira (todos os inversores) e vincula o cliente. Depois, em **Usina → Configurações →
Histórico de geração**, dá para importar os dias anteriores.

"Apagar" uma usina só a **desativa**: ela some do sistema, mas o histórico fica no banco e volta se a
SN de um inversor dela for cadastrada de novo.

---

## Estrutura

```
Monitoramento/
├── README.md
├── CLAUDE.md                  identidade visual da W.L Energy (cores, fontes, componentes)
├── backend/                   Django
│   ├── backend/               configuração (settings.py, urls.py)
│   ├── usuarios/              login, perfis, permissões, API de usuários
│   ├── usinas/                usinas, inversores, geração esperada, API de usinas
│   ├── monitoramento/         leituras (particionadas por mês), geração diária, alertas, dashboard
│   ├── integracoes/           FoxESS e Huawei: clientes das APIs, cadastro por SN, coleta, comandos
│   ├── requirements.txt       versões exatas dos pacotes Python
│   ├── .env.example           modelo das configurações (sem senhas)
│   └── .env                   configurações reais — NÃO vai para o git
└── frontend/                  Angular
    ├── src/app/pages/         login, shell (layout), visao-geral, usinas, usina-detalhe, clientes
    ├── src/app/services/      chamadas à API, login (JWT), gráficos, tema
    └── proxy.conf.json        em desenvolvimento, encaminha /api para o Django
```

Cada app do Django segue o mesmo padrão: `models.py` (tabelas), `serializers.py` (JSON),
`views.py` + `urls.py` (rotas da API), `admin.py` (telas do /admin), `tests*.py` e `migrations/`.

---

## Instalação (computador novo)

**Pré-requisitos:** Git, Python 3.11, Node 22 e PostgreSQL 17.

### 1. Código
```powershell
git clone https://github.com/RicardoWLEnergy/Monitoramento.git
cd Monitoramento
```

### 2. Banco de dados
Instale o PostgreSQL 17 (`winget install --id PostgreSQL.PostgreSQL.17 --interactive`) e, conectado
como `postgres` (ex.: no Beekeeper), rode **um comando por vez**:
```sql
CREATE ROLE wl_monitoramento WITH LOGIN PASSWORD 'escolha-uma-senha';
ALTER ROLE wl_monitoramento CREATEDB;   -- necessário para os testes automáticos
CREATE DATABASE monitoramento OWNER wl_monitoramento ENCODING 'UTF8' TEMPLATE template0;
```

### 3. Configurações (`backend/.env`)
```powershell
copy backend\.env.example backend\.env
```
Preencha:
- `DJANGO_SECRET_KEY` — gere uma nova (comando no passo 4);
- `DATABASE_URL` — `postgres://wl_monitoramento:SENHA@localhost:5432/monitoramento`;
- `FOXESS_API_KEY` e `HUAWEI_*` — copie do ambiente atual **por um meio seguro** (nunca pelo git).

### 4. Backend
```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r backend\requirements.txt
cd backend
..\venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
..\venv\Scripts\python.exe manage.py migrate
..\venv\Scripts\python.exe manage.py createsuperuser
..\venv\Scripts\python.exe manage.py test
```
O `migrate` cria as tabelas (inclusive as partições mensais das leituras). O `test` deve terminar com `OK`.

### 5. Frontend
```powershell
cd ..\frontend
npm install
```

---

## Rodando (três terminais)

```powershell
# 1) API — http://localhost:8000  (painel: /admin)
cd backend;  ..\venv\Scripts\python.exe manage.py runserver

# 2) Telas — http://localhost:4200
cd frontend; npm start

# 3) Coleta automática (opcional em desenvolvimento)
cd backend;  ..\venv\Scripts\python.exe manage.py coletar
```

O coletor fica rodando até `Ctrl + C`. Só um coletor pode rodar por vez (há uma trava no banco).

---

## Comandos úteis (`backend/`, com `..\venv\Scripts\python.exe manage.py ...`)

| Comando | Para quê |
|---|---|
| `coletar` | coleta automática: tempo real a cada 5 min + rotina diária (energia dos últimos dias, curva de ontem, partições) |
| `coletar --uma-vez` | um ciclo completo e sai (bom para testar) |
| `importar_historico [--usina ID] [--meses 13] [--dias 30]` | importa histórico de energia diária e curvas |
| `vincular_inversor EMAIL SN --plataforma foxess\|huawei` | mesmo cadastro da tela de Clientes, pelo terminal |
| `testar_integracao foxess\|huawei [--usina NOME] [--bruto]` | testa a conexão com a plataforma, **só leitura** |
| `particoes_leitura` | cria as partições dos próximos meses e remove as antigas (o coletor já faz isso todo dia) |
| `test` | roda os testes automáticos (nenhum acessa as APIs reais) |

---

## Integrações

### FoxESS Cloud (inclui inversores WEG)
- Credencial: **API key** da conta de instalador (portal → perfil → *API Management*).
  Gerar uma nova chave invalida a anterior.
- Limites: 1 chamada por segundo por rota; 1.440 chamadas por dia por inversor.
- Não há dados por usina na API: tudo vem por inversor e o sistema soma.
- Inversores com modelo `SIW…` são WEG.

### Huawei FusionSolar (Northbound API)
- Credencial: **conta Northbound** (*System → Company Management → Northbound Management*),
  diferente do login normal do portal. Host: o mesmo do portal após o login (ex.: `la5.fusionsolar.huawei.com`).
- **Uma conta Northbound por ambiente**: a Huawei derruba a sessão se a mesma conta for usada em dois
  lugares ao mesmo tempo (ex.: seu computador e o servidor).
- 5 senhas erradas em 10 minutos bloqueiam a conta por 30 minutos.
- A curva de 5 min do **histórico** (`getDevHistoryKpi`) ainda não está liberada na conta atual (erro 401):
  a energia diária funciona, e a curva de 5 min se forma pela coleta de tempo real daqui para frente.

---

## Dados e backup

Os dados ficam só no PostgreSQL local. Para copiar o banco para outro computador:
```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe" -U wl_monitoramento -d monitoramento -F c -f monitoramento.backup
& "C:\Program Files\PostgreSQL\17\bin\pg_restore.exe" -U wl_monitoramento -d monitoramento monitoramento.backup
```
O arquivo `.backup` contém dados de clientes (CPF, endereço): transporte com cuidado e **nunca** o
coloque no git.

As leituras de 5 min são mantidas por 13 meses (`LEITURAS_RETENCAO_MESES`); a energia diária, para sempre.

---

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| Tela mostra "Sem conexão com o servidor" | o Django não está rodando (`runserver`) |
| Erro 500 em todas as chamadas `/api` no Angular | o proxy deve apontar para `127.0.0.1:8000` (não `localhost`) — ver `frontend/proxy.conf.json` |
| Huawei: `failCode=20400` no login | usuário/senha não são da conta **Northbound**, ou host errado |
| Huawei: `failCode=401` | interface não liberada na conta Northbound |
| FoxESS: `errno=41200` | instabilidade da FoxESS em uma rota; o cadastro já contorna |
| `Já existe um coletor rodando` | outro `coletar` está aberto; encerre-o antes |
| Inserir leitura dá erro de partição | rode `particoes_leitura` (o coletor faz isso todo dia) |
