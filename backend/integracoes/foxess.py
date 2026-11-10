"""
Cliente da FoxESS Cloud OpenAPI.

Documentação oficial: https://www.foxesscloud.com/public/i18n/en/OpenApiDocument.html

Regras principais (doc v1.1.18):
- Cada chamada é assinada: md5( path + "\\r\\n" + api_key + "\\r\\n" + timestamp_ms ).
  ATENÇÃO: o "\\r\\n" são os 4 caracteres literais (barra, r, barra, n), não uma quebra de linha.
  Assina-se só o path (sem domínio e sem ?query).
- Limite: 1 chamada por segundo POR endpoint; 1440 chamadas/dia por inversor.
- Erro vem no campo "errno" (HTTP costuma ser 200). errno 0 = sucesso.
- Não há dados agregados por usina: potência e energia são por inversor (SN).
- Unidades: potência em kW, energia em kWh.
"""
import hashlib
import threading
import time
from datetime import datetime

import requests

USER_AGENT = 'WL-Monitoramento/1.0 (+https://wlenergy.com.br)'

# Erros mais comuns (tabela completa: GET /c/v0/errors/message)
ERROS = {
    40256: 'Cabeçalhos ausentes ou inválidos',
    40257: 'Parâmetros inválidos',
    40400: 'Requisições muito frequentes (limite por segundo)',
    40401: 'Login muito frequente',
    40402: 'Limite de chamadas excedido (cota diária)',
    40403: 'Requisições demais',
    41808: 'API key inválida',
    41809: 'API key ilegal',
    41811: 'Sem permissão para esta operação',
    41930: 'Inversor não existe ou não pertence a esta conta',
}
ERROS_DE_LIMITE = {40400, 40402, 40403}

# Estado de operação do inversor (variável runningState)
ESTADOS = {
    160: 'autoteste', 161: 'aguardando', 162: 'verificando', 163: 'conectado à rede',
    164: 'fora da rede', 165: 'falha', 166: 'falha permanente', 167: 'standby',
    168: 'atualizando', 169: 'teste de fábrica', 170: 'estado ilegal',
}

# Variáveis de tempo real que usamos
VARIAVEIS_TEMPO_REAL = [
    'generationPower',     # kW — potência CA entregue
    'pvPower',             # kW — potência CC dos painéis
    'todayYield',          # kWh — energia do dia (a doc diz "kW", mas é kWh)
    'generation',          # kWh — energia acumulada
    'runningState',        # estado (ver ESTADOS)
    'currentFault',        # códigos de falha atuais
    'currentFaultCount',
    'invTemperation',      # °C
]


class FoxESSErro(Exception):
    def __init__(self, path: str, errno: int | None, mensagem: str = ''):
        self.path, self.errno = path, errno
        descricao = ERROS.get(errno or 0, mensagem or 'erro desconhecido')
        super().__init__(f'FoxESS {path}: errno={errno} — {descricao}')

    @property
    def e_limite(self) -> bool:
        return self.errno in ERROS_DE_LIMITE


class FoxESSCliente:
    """Faz as chamadas assinadas respeitando 1 chamada/segundo por endpoint."""

    INTERVALO_POR_ENDPOINT = 1.05  # segundos (folga sobre o limite de 1/s)

    def __init__(self, base_url: str, api_key: str, timeout: int = 30):
        if not api_key:
            raise ValueError('FOXESS_API_KEY não configurada no .env.')
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.timeout = timeout
        self.sessao = requests.Session()
        self._ultima_chamada: dict[str, float] = {}
        self._trava = threading.Lock()

    # ---------- infraestrutura ----------
    def assinatura(self, path: str, timestamp: str) -> str:
        texto = rf'{path}\r\n{self.api_key}\r\n{timestamp}'  # \r\n LITERAIS (raw string)
        return hashlib.md5(texto.encode('utf-8')).hexdigest()

    def _cabecalhos(self, path: str) -> dict:
        timestamp = str(round(time.time() * 1000))
        return {
            'token': self.api_key,
            'timestamp': timestamp,
            'signature': self.assinatura(path, timestamp),
            'lang': 'en',
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
        }

    def _aguardar_vez(self, path: str) -> None:
        with self._trava:
            espera = self._ultima_chamada.get(path, 0) + self.INTERVALO_POR_ENDPOINT - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._ultima_chamada[path] = time.monotonic()

    def chamar(self, metodo: str, path: str, params: dict | None = None, corpo: dict | None = None):
        self._aguardar_vez(path)
        resposta = self.sessao.request(
            metodo, self.base_url + path, headers=self._cabecalhos(path),
            params=params, json=corpo, timeout=self.timeout,
        )
        if resposta.status_code == 401:
            raise FoxESSErro(path, 41808)
        resposta.raise_for_status()
        dados = resposta.json()
        if dados.get('errno') != 0:
            raise FoxESSErro(path, dados.get('errno'), dados.get('msg', ''))
        return dados.get('result')

    def _paginar(self, path: str, tamanho: int = 100) -> list[dict]:
        pagina, itens = 1, []
        while True:
            r = self.chamar('POST', path, corpo={'currentPage': pagina, 'pageSize': tamanho})
            itens += r.get('data') or []
            if pagina * int(r.get('pageSize') or tamanho) >= int(r.get('total') or 0):
                return itens
            pagina += 1

    # ---------- conta ----------
    def cota(self) -> dict:
        """Chamadas restantes no dia: {'total': ..., 'remaining': ...}."""
        return self.chamar('GET', '/op/v0/user/getAccessCount')

    # ---------- usinas ----------
    def listar_usinas(self) -> list[dict]:
        """[{stationID, name, ianaTimezone}, ...]"""
        return self._paginar('/op/v0/plant/list')

    def detalhe_usina(self, id_usina: str) -> dict:
        """stationName, city, address, capacity (kW), timezone, modules[{moduleSN, deviceSN}], ..."""
        return self.chamar('GET', '/op/v0/plant/detail', params={'id': id_usina})

    # ---------- inversores ----------
    def listar_inversores(self) -> list[dict]:
        """[{deviceSN, stationID, stationName, status (1 online, 2 falha, 3 offline), deviceType, ...}]"""
        return self._paginar('/op/v0/device/list')

    def detalhe_inversor(self, sn: str) -> dict:
        """Inclui capacity (kW nominal) e status."""
        return self.chamar('GET', '/op/v1/device/detail', params={'sn': sn})

    def tempo_real(self, sns: list[str], variaveis: list[str] | None = None) -> list[dict]:
        """Até 50 SNs por chamada (o cliente divide em lotes)."""
        resultado = []
        for i in range(0, len(sns), 50):
            resultado += self.chamar('POST', '/op/v1/device/real/query', corpo={
                'sns': sns[i:i + 50], 'variables': variaveis or VARIAVEIS_TEMPO_REAL,
            }) or []
        return resultado

    def historico(self, sn: str, inicio: datetime, fim: datetime, variaveis: list[str] | None = None) -> list[dict]:
        """Curva de um inversor (janela máxima de 24 h por chamada; horários devolvidos em UTC)."""
        return self.chamar('POST', '/op/v0/device/history/query', corpo={
            'sn': sn, 'variables': variaveis or ['generationPower'],
            'begin': int(inicio.timestamp() * 1000), 'end': int(fim.timestamp() * 1000),
        })

    def geracao(self, sn: str) -> dict:
        """{'today', 'month', 'cumulative'} em kWh, no fuso da usina."""
        return self.chamar('GET', '/op/v0/device/generation', params={'sn': sn})

    def relatorio_mensal(self, sn: str, ano: int, mes: int) -> list[dict]:
        """Energia de cada dia do mês (kWh)."""
        return self.chamar('POST', '/op/v0/device/report/query', corpo={
            'sn': sn, 'year': ano, 'month': mes, 'dimension': 'month', 'variables': ['generation'],
        })
