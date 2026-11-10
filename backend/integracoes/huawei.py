"""
Cliente da Huawei FusionSolar — Northbound API ("thirdData").

Referência: iMaster NetEco / SmartPVMS Northbound Interface Reference.

Regras principais (ver o estudo das APIs):
- Endereço: o mesmo host do portal web da empresa + /thirdData (ex.: https://la5.fusionsolar.huawei.com/thirdData).
- Login: POST /login {"userName", "systemCode"(= senha)} → token no cabeçalho de resposta XSRF-TOKEN.
  O token vale 30 min e vai em todas as chamadas no cabeçalho XSRF-TOKEN.
  Limite: 5 logins a cada 10 min (o cliente reaproveita o token e só reloga quando expira).
- Todas as chamadas são POST com JSON. Listas de IDs vão como texto separado por vírgula.
- Erro vem em "failCode" (HTTP costuma ser 200): 305 = sessão expirada (reloga e repete),
  407 = acessos frequentes demais, 401 = interface não liberada para a conta.
- Lotes: até 100 usinas/dispositivos por chamada; histórico de 5 min: até 10 dispositivos e 3 dias.
- Limite de frequência: cerca de 1 chamada por minuto por interface (a ser confirmado com a conta real).
"""
import threading
import time
from datetime import datetime

import requests

USER_AGENT = 'WL-Monitoramento/1.0 (+https://wlenergy.com.br)'

ERROS = {
    305: 'Sessão expirada (é preciso logar de novo)',
    401: 'Interface não liberada para esta conta Northbound',
    407: 'Acessos frequentes demais (limite da Huawei)',
    20001: 'Sistema/usuário Northbound inexistente',
    20002: 'Usuário Northbound bloqueado',
    20003: 'Usuário Northbound expirado',
    20056: 'Usina sem autorização do proprietário para acesso via API',
}

# Tipos de dispositivo (devTypeId)
TIPO_INVERSOR_STRING = 1
TIPO_INVERSOR_RESIDENCIAL = 38
TIPOS_INVERSOR = (TIPO_INVERSOR_STRING, TIPO_INVERSOR_RESIDENCIAL)

# Estado do inversor (inverter_state) — os mais comuns
ESTADOS = {
    512: 'conectado à rede', 513: 'conectado (limitado)', 514: 'conectado (limitado)',
    768: 'desligado: falha', 769: 'desligado: comando', 770: 'desligado: OVGR', 771: 'desligado: comunicação',
    40960: 'standby: sem irradiância', 45056: 'comunicação interrompida',
}

# Saúde da usina (real_health_state)
SAUDE = {1: 'desconectada', 2: 'com falha', 3: 'saudável'}


class HuaweiErro(Exception):
    def __init__(self, endpoint: str, codigo: int | None, mensagem: str = ''):
        self.endpoint, self.codigo = endpoint, codigo
        descricao = ERROS.get(codigo or 0, mensagem or 'erro desconhecido')
        super().__init__(f'Huawei {endpoint}: failCode={codigo} — {descricao}')

    @property
    def e_limite(self) -> bool:
        return self.codigo == 407


def em_lotes(itens: list, tamanho: int):
    for i in range(0, len(itens), tamanho):
        yield itens[i:i + tamanho]


def ms(momento: datetime) -> int:
    """datetime → milissegundos (formato de tempo da Huawei)."""
    return int(momento.timestamp() * 1000)


class HuaweiCliente:
    """Faz login, guarda o token e respeita um intervalo mínimo por interface."""

    INTERVALO_POR_ENDPOINT = 1.0   # segundos; ajustar após o teste com a conta real

    def __init__(self, base_url: str, usuario: str, senha: str, timeout: int = 60):
        if not usuario or not senha:
            raise ValueError('HUAWEI_USUARIO e HUAWEI_SENHA não configurados no .env.')
        self.base_url = base_url.rstrip('/')
        self.usuario, self.senha = usuario, senha
        self.timeout = timeout
        self.sessao = requests.Session()
        self.sessao.headers.update({'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
        self.token: str | None = None
        self.chamadas = 0
        self._ultima_chamada: dict[str, float] = {}
        self._trava = threading.Lock()

    # ---------- infraestrutura ----------
    def login(self) -> None:
        resposta = self.sessao.post(f'{self.base_url}/login', json={'userName': self.usuario, 'systemCode': self.senha},
                                    timeout=self.timeout)
        self.chamadas += 1
        resposta.raise_for_status()
        dados = resposta.json() if resposta.content else {}
        token = resposta.headers.get('xsrf-token') or resposta.cookies.get('XSRF-TOKEN')
        if not token or dados.get('failCode') not in (0, None) or dados.get('success') is False:
            raise HuaweiErro('login', dados.get('failCode'), dados.get('message') or 'usuário ou senha inválidos')
        self.token = token
        self.sessao.headers['XSRF-TOKEN'] = token

    def _aguardar_vez(self, endpoint: str) -> None:
        with self._trava:
            espera = self._ultima_chamada.get(endpoint, 0) + self.INTERVALO_POR_ENDPOINT - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._ultima_chamada[endpoint] = time.monotonic()

    def chamar(self, endpoint: str, corpo: dict | None = None, _tentativa: int = 1):
        if not self.token:
            self.login()
        self._aguardar_vez(endpoint)
        resposta = self.sessao.post(f'{self.base_url}/{endpoint}', json=corpo or {}, timeout=self.timeout)
        self.chamadas += 1
        resposta.raise_for_status()
        dados = resposta.json()
        codigo = dados.get('failCode')
        if codigo == 305 and _tentativa == 1:          # token expirou: reloga uma vez e repete
            self.token = None
            return self.chamar(endpoint, corpo, _tentativa=2)
        if codigo not in (0, None) or dados.get('success') is False:
            raise HuaweiErro(endpoint, codigo, dados.get('message') or '')
        return dados.get('data')

    # ---------- usinas ----------
    def listar_usinas(self) -> list[dict]:
        """Paginado (/stations): plantCode, plantName, plantAddress, capacity, latitude, longitude..."""
        pagina, itens = 1, []
        while True:
            dados = self.chamar('stations', {'pageNo': pagina, 'pageSize': 100}) or {}
            itens += dados.get('list') or []
            if pagina >= int(dados.get('pageCount') or 1):
                return itens
            pagina += 1

    def tempo_real_usinas(self, codigos: list[str]) -> list[dict]:
        """day_power, month_power, total_power (kWh), real_health_state (1 desconectada, 2 falha, 3 saudável)."""
        resultado = []
        for lote in em_lotes(codigos, 100):
            resultado += self.chamar('getStationRealKpi', {'stationCodes': ','.join(lote)}) or []
        return resultado

    def kpi_diario(self, codigos: list[str], dia_do_mes: datetime) -> list[dict]:
        """Energia de TODOS os dias do mês que contém `dia_do_mes` (inverter_power, kWh)."""
        resultado = []
        for lote in em_lotes(codigos, 100):
            resultado += self.chamar('getKpiStationDay', {'stationCodes': ','.join(lote),
                                                          'collectTime': ms(dia_do_mes)}) or []
        return resultado

    # ---------- dispositivos ----------
    def listar_dispositivos(self, codigos: list[str]) -> list[dict]:
        """id (devId), devName, stationCode, esnCode (SN), devTypeId, invType (modelo)..."""
        resultado = []
        for lote in em_lotes(codigos, 100):
            resultado += self.chamar('getDevList', {'stationCodes': ','.join(lote)}) or []
        return resultado

    def tempo_real_dispositivos(self, ids: list, tipo: int) -> list[dict]:
        """active_power, day_cap, total_cap, run_state, inverter_state... (até 100 do mesmo tipo)."""
        resultado = []
        for lote in em_lotes([str(i) for i in ids], 100):
            resultado += self.chamar('getDevRealKpi', {'devIds': ','.join(lote), 'devTypeId': tipo}) or []
        return resultado

    def historico_dispositivos(self, ids: list, tipo: int, inicio: datetime, fim: datetime) -> list[dict]:
        """Registros de 5 min (active_power...). Até 10 dispositivos e 3 dias por chamada."""
        resultado = []
        for lote in em_lotes([str(i) for i in ids], 10):
            resultado += self.chamar('getDevHistoryKpi', {
                'devIds': ','.join(lote), 'devTypeId': tipo, 'startTime': ms(inicio), 'endTime': ms(fim),
            }) or []
        return resultado

    def alarmes(self, codigos: list[str], inicio: datetime, fim: datetime) -> list[dict]:
        resultado = []
        for lote in em_lotes(codigos, 100):
            resultado += self.chamar('getAlarmList', {
                'stationCodes': ','.join(lote), 'beginTime': ms(inicio), 'endTime': ms(fim), 'language': 'pt_BR',
            }) or []
        return resultado
