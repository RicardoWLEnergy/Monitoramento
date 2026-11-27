# Monitoramento · W.L Energy

Sistema de monitoramento das usinas fotovoltaicas da W.L Energy. Ele coleta a geração diretamente
das plataformas dos fabricantes (**FoxESS Cloud** — inclui os inversores WEG —, **Huawei FusionSolar** e **Sungrow iSolarCloud**)
e mostra tudo em um painel web com acesso por perfil.

| Camada | Tecnologia |
|---|---|
| Backend (API) | Django 5.2 + Django REST Framework + login JWT |
| Banco de dados | PostgreSQL 17 |
| Frontend (telas) | Angular 19 + ECharts (gráficos) + Lucide (ícones) |
| Coleta | comando `coletar` (tempo real a cada 5 min + rotina diária) |
| Produção | Docker Compose + Caddy (HTTPS) — **https://monitoramento.wlenergy.com.br** |

A seção **Instalação** abaixo é para desenvolvimento num computador; o servidor está em **Produção (Docker)**.

---

## Perfis de acesso

| Perfil | O que pode fazer |
|---|---|
| **Admin** | tudo: usuários, alertas, geração esperada, apagar usinas |
| **Colaborador** | vê todas as usinas, cadastra clientes, vincula usinas pela SN, importa histórico |
| **Cliente** | vê só as usinas vinculadas a ele |

As regras ficam em um só lugar: `backend/usuarios/permissoes.py`.

### Login
- **E-mail + senha** ou **e-mail + código pelo WhatsApp**: o sistema envia um código de 6 números ao
  WhatsApp cadastrado naquele e-mail e mostra o final do número (ex.: "(61) * ****-0142").
  O código vale 5 minutos, uma única vez, e é bloqueado após 5 tentativas erradas; no máximo
  1 envio por minuto e 5 por hora. O banco guarda só o hash do código.
- **Fechar o navegador encerra a sessão.** Guias abertas ao mesmo tempo compartilham o login; sair em
  uma sai de todas. Validade máxima do login: 12 horas (`JWT_REFRESH_HOURS`).

## Como uma usina entra no sistema

Só entra no banco o que for cadastrado. Em **Clientes → Novo cliente**, informe os dados do cliente,
a **plataforma** e a **SN de um inversor**. O sistema busca a usina daquela SN na plataforma, grava a
usina inteira (todos os inversores) e vincula o cliente. Depois, em **Usina → Configurações →
Histórico de geração**, dá para importar os dias anteriores.

A importação de histórico roda **no servidor, em segundo plano**: o botão só coloca o pedido na fila e
a página pode ser fechada. Quem importa é o **coletor** (`manage.py coletar`), em pedaços (1 mês de
energia ou 1 dia de curva por vez), só no tempo livre entre os ciclos de tempo real: o monitoramento ao
vivo tem prioridade. Se o coletor reiniciar, a importação continua de onde parou. Em desenvolvimento,
o coletor precisa estar aberto num terminal, senão o pedido fica "Na fila".

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
│   ├── integracoes/           FoxESS, Huawei e Sungrow: clientes das APIs, cadastro por SN, coleta, comandos
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
| `coletar` | coleta automática: tempo real a cada 5 min + rotina diária (energia dos últimos dias, curva de ontem, partições) + importações de histórico pedidas na tela |
| `coletar --uma-vez` | um ciclo completo e sai (bom para testar) |
| `atualizar_clima [--dias 90]` | preenche o clima do dia (ensolarado/nublado/chuvoso, Open-Meteo) dos dias passados; o coletor já atualiza ontem e hoje a cada 3 h |
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

### Sungrow iSolarCloud (OpenAPI, modo usuário)
- Aplicação criada no portal de desenvolvedor (developer-api.isolarcloud.com), região internacional
  (`gateway.isolarcloud.com.hk`). No `.env`: `SUNGROW_APPKEY`, `SUNGROW_ACCESS_KEY` (a *secret key* da
  aplicação), `SUNGROW_USUARIO` e `SUNGROW_SENHA` (login da conta da W.L no iSolarCloud).
- O sistema faz login sozinho; o token vale 24 h e se renova a cada chamada. Vencido (E00003), loga de novo.
- **Senhas erradas repetidas bloqueiam a conta**: depois de um login recusado o sistema para de tentar
  por 30 min (vale para o coletor e para o cadastro).
- Limites: E901 (frequente demais), E999 (por hora), E998 (por mês) — o coletor para e tenta no próximo ciclo.
- Tempo real por inversor; energia diária e curva de 5 min por usina (ps_key `{ps_id}_11_0_0`).
  O histórico não traz o dia de hoje.

### Google (planilha OBRAS e documentos da tela "Meu projeto")
O cliente vê o andamento da obra pela linha da aba **OBRAS** cujo **Nº OBRA** = ID do cliente (campo do
cadastro). O servidor lê a planilha (no máximo a cada 5 min) e entrega os documentos do Drive; o cliente nunca
vê valor, vendedor, nota fiscal etc., nem os links do Drive.

Configuração (uma vez), com uma **conta de serviço** (usuário robô só de leitura):
0. Se o Google recusar criar a chave ("A criação de chaves de conta de serviço está desativada"), o TI
   precisa liberar a política **iam.disableServiceAccountKeyCreation** SÓ no projeto do sistema
   (Políticas da organização → Gerenciar política → Substituir a do pai → Desativada; exige o papel
   "Administrador de políticas da organização"). Depois de criar a chave, pode reativar: a chave continua valendo.
1. **Google Cloud** (console.cloud.google.com) → criar um projeto → *APIs e serviços* → ativar
   **Google Sheets API** e **Google Drive API**.
2. *IAM e administrador → Contas de serviço* → **Criar conta de serviço** (sem papéis) → abrir a conta →
   *Chaves* → **Adicionar chave → JSON** (baixa um arquivo `.json`; guarde em local seguro, nunca no git).
3. **Compartilhar** a planilha e a pasta dos documentos no Drive com o e-mail da conta de serviço
   (`...@...iam.gserviceaccount.com`) como **Leitor**.
4. No `.env`: `GOOGLE_CREDENCIAIS` = conteúdo do `.json` em base64 (PowerShell:
   `[Convert]::ToBase64String([IO.File]::ReadAllBytes("chave.json"))`; Linux: `base64 -w0 chave.json`)
   e `PLANILHA_OBRAS_ID` = o código no endereço da planilha (`/spreadsheets/d/<CÓDIGO>/edit`).
5. Na aba OBRAS, colunas com o **ID do arquivo no Drive** de cada documento (o código no link
   `/file/d/<ID>/view`): `ID ART`, `ID PARECER DE ACESSO`, `ID PRANCHA`, `ID COMISSIONAMENTO N1`,
   `ID COMISSIONAMENTO N2`. Vazia = "disponível em breve" na tela.

Regras: etapa atual = coluna **ETAPA ENGENHARIA**; as datas dizem quando cada etapa terminou; prazo da
vistoria = **VISTORIA TÉCNICA** + 7 dias úteis (Neoenergia) ou 5 (Equatorial), sem fins de semana e feriados
nacionais. A equipe vê o projeto de qualquer cliente em **Meu projeto** (campo "ID do cliente").

### uazapi (WhatsApp, código de acesso no login)
- Variáveis no `.env`: `UAZAPI_URL` (endereço do servidor, no painel da uazapi) e `UAZAPI_TOKEN`
  (token da **instância**, não o admintoken). Vazias = a opção de código responde "indisponível".
- Envio: `POST {UAZAPI_URL}/send/text` (doc: https://docs.uazapi.com/reference/sendText.md).
- A instância precisa estar conectada ao WhatsApp no painel da uazapi; falhas ficam no registro do
  servidor (sem o token) e a tela pede para tentar de novo ou entrar com a senha.

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

## Produção (Docker)

No ar em **https://monitoramento.wlenergy.com.br** — servidor Ubuntu com Docker Compose.
O código fica em `~/monitoramento` no servidor (clonado do GitHub por uma Deploy Key só de leitura).

### Como funciona
```
Internet ──HTTPS──► web (Caddy) ─┬─ /api, /static → backend (Django + Gunicorn)
                                 └─ resto         → telas do Angular (já compiladas)
Servidor (só dentro dele) ── 127.0.0.1:8001 → backend  (painel /admin, por túnel SSH)
                    backend ──► db (PostgreSQL 17, volume dados_postgres)
                    coletor ──► db   (manage.py coletar: FoxESS/Huawei/Sungrow a cada 5 min)
                    backup  ──► db   (pg_dump diário em ./backups, mantém 14 dias)
```
| Arquivo | Papel |
|---|---|
| `docker-compose.yml` | os 5 contêineres (db, backend, coletor, web, backup) |
| `Caddyfile` | HTTPS automático, cabeçalhos de segurança e encaminhamento `/api`, `/static` → Django |
| `backend/Dockerfile` | imagem do Django (usada pela API e pelo coletor) |
| `frontend/Dockerfile` | compila o Angular e entrega pelo Caddy |
| `backend/.env.example` | modelo das configurações; no servidor vira `.env` na raiz do projeto (fora do git) |

Só o Caddy fica aberto para a internet (portas 80/443). O banco não tem porta publicada.
O painel `/admin` do Django **não** fica na internet: só pelo próprio servidor (ver "Painel /admin").

### Primeira instalação (servidor novo)
1. Ubuntu atualizado, **swap de 2 GB**, firewall `ufw` liberando só OpenSSH, 80 e 443.
2. Docker + plugin Compose (repositório oficial do Docker ou `docker.io` + `docker-compose-v2` do Ubuntu).
3. Deploy Key: `ssh-keygen` no servidor → GitHub → *Settings → Deploy keys* (sem escrita) →
   `git clone git@github.com:RicardoWLEnergy/Monitoramento.git ~/monitoramento`.
4. `cp backend/.env.example .env` e preencher, inclusive a parte "Só no servidor" do fim do arquivo (chave e senha
   geradas com `openssl rand -hex 50` / `-hex 24`; a senha do banco deve ter só letras e números).
5. Subir:
   ```bash
   docker compose up -d --build
   docker compose exec backend python manage.py migrate
   docker compose exec backend python manage.py createsuperuser
   ```
O domínio precisa apontar para o IP do servidor **antes** de subir: o Caddy pede o certificado sozinho.

### Atualizar o sistema (depois de um push)
```bash
cd ~/monitoramento
git pull
docker compose up -d --build
docker compose exec backend python manage.py migrate
```
Mudou só o `Caddyfile`? Valide e reinicie: `docker compose run --rm web caddy validate --config
/etc/caddy/Caddyfile --adapter caddyfile` e depois `docker compose restart web`. Se mudou também algo em
`frontend/` (ex.: `public/manutencao.html`), é preciso recompilar: `docker compose up -d --build web`.

### Página de manutenção
- **Automática:** enquanto a API reinicia (ex.: durante o `up -d --build`) ou se ela cair, quem estiver usando
  vê a página "Estamos atualizando o sistema", que confere a cada 15 s e volta sozinha para a tela de antes.
- **Planejada:** para colocar o sistema todo em manutenção (ex.: antes de uma migração grande):
  ```bash
  touch manutencao/manutencao.ligada                           # liga (a pasta já vem no repositório)
  rm manutencao/manutencao.ligada                              # desliga
  ```
  Vale na hora (não precisa reiniciar nada). O `/admin` pelo túnel SSH continua funcionando.
- Se o **servidor inteiro** cair, a página não aparece (não há quem responda).
- Depois de uma atualização, quem estava com o sistema aberto recarrega sozinho para a versão nova.

### Painel /admin (só pelo servidor)
O backend escuta em `127.0.0.1:8001` **dentro** do servidor. Do seu computador, abra um túnel SSH:
```bash
ssh -L 8001:127.0.0.1:8001 usuario@IP_DO_SERVIDOR
```
e, com o terminal aberto, acesse **http://localhost:8001/admin/**. Requisitos no `.env` do servidor:
`DJANGO_ALLOWED_HOSTS` com `localhost` (ex.: `monitoramento.wlenergy.com.br,localhost`).

### Segurança em produção
- **Login:** até 10 tentativas por minuto por IP; 10 senhas erradas no mesmo e-mail bloqueiam o login com
  senha por 15 min. Trocar a senha derruba os logins abertos. Os contadores ficam na tabela `cache_sistema`
  (criada pelo `migrate`).
- **Chave secreta:** o sistema não inicia em produção com a chave de exemplo ou curta.
- **Cabeçalhos:** HSTS (só HTTPS) e uma política de conteúdo (CSP) em modo "só observa". Depois de alguns
  dias sem avisos no console do navegador (F12), trocar `Content-Security-Policy-Report-Only` por
  `Content-Security-Policy` no `Caddyfile` e `docker compose restart web`. Se o script de tema do
  `frontend/src/index.html` mudar, atualizar o hash `sha256-...` dele no `Caddyfile`.
- **Backups:** gravados só para o dono; deixe a pasta fechada: `chmod 700 backups`. Falha aparece em
  `docker compose logs backup` como "BACKUP FALHOU". Recomendado: copiar para fora da VPS.

### Comandos do dia a dia (no servidor, em `~/monitoramento`)
| Para | Comando |
|---|---|
| Ver os contêineres | `docker compose ps` |
| Registros do coletor | `docker compose logs -f coletor` (sair com `Ctrl + C`) |
| Registros da API | `docker compose logs --tail 50 backend` |
| Comando do Django | `docker compose exec backend python manage.py <comando>` |
| Reiniciar uma parte | `docker compose restart <serviço>` |
| Parar tudo (os dados ficam) | `docker compose down` |
| Ver os backups | `ls -lh backups/` |

### Cuidados
- **Huawei**: a conta Northbound roda no servidor — não usar a mesma conta em outro lugar ao mesmo tempo
  (nem o coletor local).
- **Nunca** publicar a porta do banco como `"5432:5432"`: o Docker passa por cima do `ufw` e a exporia à internet.
  Para acessar pelo Beekeeper, publicar só em `127.0.0.1` e usar túnel SSH.
- O `.env` do servidor tem todas as senhas: nunca copiar para o git nem enviar por mensagem.

---

## Problemas comuns

| Sintoma | Causa / solução |
|---|---|
| Tela mostra "Sem conexão com o servidor" | o Django não está rodando (`runserver`) |
| Erro 500 em todas as chamadas `/api` no Angular | o proxy deve apontar para `127.0.0.1:8000` (não `localhost`) — ver `frontend/proxy.conf.json` |
| Huawei: `failCode=20400` no login | usuário/senha não são da conta **Northbound**, ou host errado |
| Huawei: `failCode=401` | interface não liberada na conta Northbound |
| Sungrow: `login` com "senha incorreta" / "conta não existe" | confira `SUNGROW_USUARIO`/`SUNGROW_SENHA`; o sistema só tenta de novo após 30 min |
| FoxESS: `errno=41200` | instabilidade da FoxESS em uma rota; o cadastro já contorna |
| `Já existe um coletor rodando` | outro `coletar` está aberto; encerre-o antes |
| Inserir leitura dá erro de partição | rode `particoes_leitura` (o coletor faz isso todo dia) |
| Produção: `/admin` abre a tela do sistema | o `Caddyfile` precisa encaminhar `/admin` (sem barra) e `/admin/*` ao Django |
| Produção: contêiner reiniciando sem parar | `docker compose logs <serviço>` mostra o motivo |
