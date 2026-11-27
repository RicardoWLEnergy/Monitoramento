"""
Cliente da Sungrow iSolarCloud — OpenAPI, modo usuário (login com usuário e senha da conta).

Regras (documentação do portal de desenvolvedor):
- Endereço da região internacional (Brasil): https://gateway.isolarcloud.com.hk
- Tudo é POST com JSON. Cabeçalhos: sys_code 901 e x-access-key (da aplicação).
  Corpo sempre com appkey, lang e o token do login (não existe cabeçalho Authorization neste modo).
- Login: POST /openapi/login. O result_code vem "1" até com senha errada: o que vale é login_state
  (1 ok · -1 conta não existe · 0 senha incorreta · 2 bloqueada por erros de senha · 5 bloqueada pelo admin).
  Senhas erradas repetidas BLOQUEIAM a conta: login recusado suspende novas tentativas por 30 min.
- O token vale 24 h e a validade se renova a cada chamada. E00003 → login de novo e repete 1 vez.
- Limites: E901 (frequente demais), E999 (por hora), E998 (por mês) → para e tenta depois (não insiste).
- Valores na menor unidade (W, Wh). O histórico não traz o dia atual; horários no fuso da usina.
- Dados da USINA usam o ps_key "{ps_id}_11_0_0" (device_type 11) nas mesmas rotas dos equipamentos.
"""
import threading
import time
from datetime import date, datetime

import requests
from django.conf import settings
from django.core.cache import cache

from .huawei import em_lotes

USER_AGENT = 'WL-Monitoramento/1.0 (+https://wlenergy.com.br)'
LANG = '_pt_BR'
SYS_CODE = '901'                      # fixo para chamadas de terceiros

# Tipos de equipamento (device_type)
TIPO_INVERSOR, TIPO_HIBRIDO = 1, 14
TIPOS_INVERSOR = (TIPO_INVERSOR, TIPO_HIBRIDO)

ERROS = {
    '-1': 'erro interno da Sungrow',
    '009': 'parâmetro obrigatório ausente',
    '010': 'valor de parâmetro inválido',
    'E00000': 'appkey inválida',
    'E00001': 'serviço da API expirado',
    'E00003': 'token inválido ou expirado',
    'E900': 'acesso não autorizado',
    'E901': 'chamadas frequentes demais',
    'E902': 'a requisição precisa ser criptografada',
    'E903': 'o IP do servidor mudou com muita frequência',
    'E998': 'limite MENSAL de chamadas atingido',
    'E999': 'limite de chamadas por HORA atingido',
}
ERROS_LIMITE = {'E901', 'E998', 'E999'}
ERROS_LOGIN = {
    '-1': 'conta não existe',
    '0': 'senha incorreta',
    '2': 'conta bloqueada por erros de senha',
    '5': 'conta bloqueada pelo administrador',
}
# Suspensão do login após uma recusa: fica no cache do banco, que vale para o coletor e para as telas
CHAVE_LOGIN_SUSPENSO = 'sungrow-login-suspenso'
PAUSA_APOS_FALHA_LOGIN = 30 * 60


def ps_key_da_usina(ps_id) -> str:
    return f'{ps_id}_11_0_0'


class SungrowErro(Exception):
    def __init__(self, endpoint: str, codigo=None, mensagem: str = ''):
        self.endpoint = endpoint
        self.codigo = str(codigo) if codigo is not None else None
        descricao = ERROS.get(self.codigo or '', '') or mensagem or 'erro desconhecido'
        super().__init__(f'Sungrow {endpoint}: {self.codigo} — {descricao}')


class SungrowLimiteErro(SungrowErro):
    """Limite de chamadas: quem chama NÃO deve insistir (tenta no próximo ciclo)."""


class SungrowLoginErro(SungrowErro):
    """Login recusado (ou suspenso): quem chama NÃO deve insistir — senhas erradas bloqueiam a conta."""

    def __init__(self, codigo=None, mensagem: str = ''):
        super().__init__('login', codigo, ERROS_LOGIN.get(str(codigo), '') or mensagem)


class _TokenInvalido(Exception):
    pass


class SungrowCliente:
    """Faz login, guarda o token e respeita um intervalo mínimo por rota."""

    INTERVALO_POR_ENDPOINT = 1.0   # segundos
    TAMANHO_LOTE = 50              # equipamentos por chamada

    def __init__(self, base_url: str | None = None, appkey: str | None = None, access_key: str | None = None,
                 usuario: str | None = None, senha: str | None = None, timeout: int = 60):
        self.appkey = appkey if appkey is not None else settings.SUNGROW_APPKEY
        access_key = access_key if access_key is not None else settings.SUNGROW_ACCESS_KEY
        self.usuario = usuario if usuario is not None else settings.SUNGROW_USUARIO
        self.senha = senha if senha is not None else settings.SUNGROW_SENHA
        if not (self.appkey and access_key and self.usuario and self.senha):
            raise ValueError('SUNGROW_APPKEY, SUNGROW_ACCESS_KEY, SUNGROW_USUARIO e SUNGROW_SENHA '
                             'não configurados no .env.')
        self.base_url = (base_url or settings.SUNGROW_API_URL).rstrip('/')
        self.timeout = timeout
        self.sessao = requests.Session()
        self.sessao.headers.update({'Content-Type': 'application/json;charset=UTF-8', 'sys_code': SYS_CODE,
                                    'x-access-key': access_key, 'User-Agent': USER_AGENT})
        self.token: str | None = None
        self._ultima_chamada: dict[str, float] = {}
        self._trava = threading.Lock()

    # ---------- infraestrutura ----------
    def _post(self, endpoint: str, corpo: dict) -> dict:
        resposta = self.sessao.post(f'{self.base_url}/openapi/{endpoint}',
                                    json={'appkey': self.appkey, 'lang': LANG, **corpo}, timeout=self.timeout)
        try:
            dados = resposta.json()
        except ValueError:
            resposta.raise_for_status()
            raise SungrowErro(endpoint, None, 'resposta inválida')
        if dados.get('result_code') == 'E00003':
            raise _TokenInvalido()
        resposta.raise_for_status()
        codigo = str(dados.get('result_code'))
        if codigo != '1':
            classe = SungrowLimiteErro if codigo in ERROS_LIMITE else SungrowErro
            raise classe(endpoint, codigo, dados.get('result_msg') or '')
        return dados.get('result_data') or {}

    def login(self) -> None:
        if cache.get(CHAVE_LOGIN_SUSPENSO):
            raise SungrowLoginErro(None, 'login suspenso por 30 min após uma recusa (evita bloquear a conta)')
        dados = self._post('login', {'user_account': self.usuario, 'user_password': self.senha})
        estado = str(dados.get('login_state'))
        if estado != '1' or not dados.get('token'):
            cache.set(CHAVE_LOGIN_SUSPENSO, True, PAUSA_APOS_FALHA_LOGIN)
            raise SungrowLoginErro(estado, dados.get('msg') or 'usuário ou senha inválidos')
        self.token = dados['token']

    def _aguardar_vez(self, endpoint: str) -> None:
        with self._trava:
            espera = self._ultima_chamada.get(endpoint, 0) + self.INTERVALO_POR_ENDPOINT - time.monotonic()
            if espera > 0:
                time.sleep(espera)
            self._ultima_chamada[endpoint] = time.monotonic()

    def chamar(self, endpoint: str, corpo: dict) -> dict:
        if not self.token:
            self.login()
        self._aguardar_vez(endpoint)
        try:
            return self._post(endpoint, {**corpo, 'token': self.token})
        except _TokenInvalido:
            self.token = None                     # token venceu: login de novo e repete uma vez
            self.login()
            try:
                return self._post(endpoint, {**corpo, 'token': self.token})
            except _TokenInvalido:
                raise SungrowErro(endpoint, 'E00003', 'token recusado mesmo depois de um login novo') from None

    # ---------- usinas ----------
    def detalhe_usina_por_sn(self, sn: str) -> dict:
        """Usina do equipamento (SN): ps_id, ps_name, ps_location, latitude, longitude, design_capacity (Wp)..."""
        return self.chamar('getPowerStationDetail', {'sn': sn}) or {}

    def detalhe_usinas(self, ps_ids: list) -> list[dict]:
        """Até 20 por chamada: ps_id, ps_name, install_power, ps_current_time_zone..."""
        resultado = []
        for lote in em_lotes([str(i) for i in ps_ids], 20):
            resultado += self.chamar('getBatchPsDetail', {'ps_ids': ','.join(lote)}).get('data_list') or []
        return resultado

    # ---------- dispositivos ----------
    def dispositivos_da_usina(self, ps_id, tipos=TIPOS_INVERSOR) -> list[dict]:
        """ps_key, device_sn, device_type, device_model_code, dev_fault_status, dev_status... (paginado)."""
        pagina, itens = 1, []
        while True:
            r = self.chamar('getDeviceList', {'ps_id': str(ps_id), 'curPage': pagina, 'size': self.TAMANHO_LOTE,
                                              'device_type_list': list(tipos)})
            lista = r.get('pageList') or []
            itens += lista
            if not lista or len(itens) >= int(r.get('rowCount') or 0):
                return itens
            pagina += 1

    def tempo_real_dispositivos(self, tipo: int, pontos: list[str], ps_keys: list[str] | None = None,
                                sns: list[str] | None = None) -> list[dict]:
        """device_point de cada equipamento (do MESMO tipo): device_time, dev_fault_status, p<ponto>..."""
        chave, valores = ('sn_list', sns) if sns else ('ps_key_list', ps_keys or [])
        itens = []
        for lote in em_lotes(list(valores), self.TAMANHO_LOTE):
            r = self.chamar('getDeviceRealTimeData', {'device_type': tipo, chave: lote, 'point_id_list': pontos})
            itens += [x.get('device_point') or {} for x in r.get('device_point_list') or []]
        return itens

    def historico_diario(self, ps_keys: list[str], ponto: str, inicio: date, fim: date) -> dict:
        """{ps_key: {'p<ponto>': [{'2': valor, 'time_stamp': 'yyyyMMdd'}]}} — pico do dia; até 100 dias."""
        return self.chamar('getDevicePointsDayMonthYearDataList', {
            'ps_key_list': ps_keys, 'data_point': f'p{ponto}', 'query_type': '1', 'data_type': '2',
            'start_time': f'{inicio:%Y%m%d}', 'end_time': f'{fim:%Y%m%d}', 'order': '0',
        })

    def historico_minuto(self, ps_keys: list[str], ponto: str, inicio: datetime, fim: datetime) -> dict:
        """{ps_key: [{'time_stamp': 'yyyyMMddHHmmss', 'p<ponto>': valor}]} a cada 5 min; janela de até 3 h."""
        return self.chamar('getDevicePointMinuteDataList', {
            'ps_key_list': ps_keys, 'points': f'p{ponto}', 'minute_interval': '5',
            'start_time_stamp': f'{inicio:%Y%m%d%H%M%S}', 'end_time_stamp': f'{fim:%Y%m%d%H%M%S}',
        })
