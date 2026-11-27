"""
Cadastro de usina a partir da SN de um inversor.

Fluxo: o Admin/Colaborador informa cliente + SN + plataforma. O sistema consulta a
plataforma, descobre a usina daquele inversor, grava a usina INTEIRA (todos os
inversores) e vincula o cliente. Só entra no banco o que for cadastrado assim.

Regras:
- Se a usina já existir, os dados técnicos são atualizados e o cliente é vinculado.
- Se ela tinha sido "apagada" (desativada), volta a ficar ativa — com todo o histórico.
- Nunca altera clientes já vinculados nem as configurações de alerta.
- Se algo falhar, nada é gravado (transação).
"""
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction

from usinas.models import Fabricante, Inversor, Plataforma, Status, Usina
from usuarios.models import Usuario

from .foxess import FoxESSCliente, FoxESSErro
from .huawei import TIPOS_INVERSOR, HuaweiCliente, HuaweiErro
from .sungrow import TIPOS_INVERSOR as TIPOS_INVERSOR_SUNGROW
from .sungrow import SungrowCliente, SungrowErro, SungrowLimiteErro, SungrowLoginErro

# status do inversor na FoxESS (device/list e device/detail)
STATUS_FOXESS = {1: Status.ONLINE, 2: Status.ALERTA, 3: Status.OFFLINE}


class CadastroErro(Exception):
    """Erro com mensagem pronta para mostrar ao usuário."""


@dataclass
class ResultadoCadastro:
    usina: Usina
    usina_nova: bool
    inversores: list[str]
    ja_vinculado: bool
    reativada: bool = False   # usina existia desativada ("apagada") e voltou


def fabricante_pelo_modelo(modelo: str) -> str:
    """Inversores SIW… são WEG (fabricados pela FoxESS); os demais da nuvem FoxESS são FoxESS."""
    return Fabricante.WEG if (modelo or '').upper().startswith('SIW') else Fabricante.FOXESS


def _decimal(valor, casas: int = 2) -> Decimal:
    try:
        return round(Decimal(str(valor)), casas)
    except Exception:
        return Decimal('0')


def status_da_usina(status_inversores: list[str]) -> str:
    """Prioridade: alerta > online > sem sol (noite) > offline."""
    for status in (Status.ALERTA, Status.ONLINE, Status.NOITE):
        if status in status_inversores:
            return status
    return Status.OFFLINE


def cadastrar_por_sn(plataforma: str, sn: str, cliente: Usuario) -> ResultadoCadastro:
    sn = (sn or '').strip().upper()
    if not sn:
        raise CadastroErro('Informe a SN do inversor.')
    if cliente.perfil != Usuario.Perfil.CLIENTE:
        raise CadastroErro('Só usuários com perfil Cliente podem ser vinculados a usinas.')

    if plataforma == Plataforma.FOXESS:
        return _cadastrar_foxess(sn, cliente)
    if plataforma == Plataforma.HUAWEI:
        return _cadastrar_huawei(sn, cliente)
    if plataforma == Plataforma.SUNGROW:
        return _cadastrar_sungrow(sn, cliente)
    raise CadastroErro(f'Plataforma desconhecida: {plataforma}')


def _coordenada(valor) -> Decimal | None:
    try:
        return round(Decimal(str(valor)), 6)
    except Exception:
        return None


def _modelo_valido(valor) -> str:
    """A FoxESS devolve '--' ou vazio quando não conhece o modelo."""
    valor = (valor or '').strip()
    return '' if valor in ('', '-', '--') else valor


def _data_valida(dia: date | None) -> date | None:
    """Só aceita datas entre 2000 e hoje (data da plataforma errada não pode parar a coleta)."""
    from django.utils import timezone
    return dia if dia and date(2000, 1, 1) <= dia <= timezone.localdate() else None


def data_criacao_foxess(texto) -> date | None:
    """createDate da FoxESS: '2024-05-23 12:35:04 BRT-0300' -> 23/05/2024."""
    try:
        return _data_valida(datetime.strptime(str(texto or '')[:10], '%Y-%m-%d').date())
    except ValueError:
        return None


def data_conexao_huawei(texto: str | None, fuso: str = 'America/Sao_Paulo') -> date | None:
    """gridConnectionDate da Huawei: '2022-11-21T16:23:00+08:00' -> data no fuso da usina."""
    try:
        momento = datetime.fromisoformat(str(texto or '').strip())
    except ValueError:
        return None
    return _data_valida(momento.astimezone(ZoneInfo(fuso)).date() if momento.tzinfo else momento.date())


def _cadastrar_foxess(sn: str, cliente: Usuario) -> ResultadoCadastro:
    """
    Fonte principal: a LISTA de inversores da conta (traz usina, status e modelo).
    O detalhe por inversor (potência nominal) é opcional: em algumas SNs a FoxESS
    responde 41200 ("Unable to load data") e o cadastro segue sem esse dado.
    """
    api = FoxESSCliente(settings.FOXESS_API_URL, settings.FOXESS_API_KEY)

    # 1) Acha o inversor na lista da conta -> usina dele
    try:
        lista = api.listar_inversores()
    except FoxESSErro as erro:
        raise CadastroErro(f'Falha ao consultar a FoxESS: {erro}') from erro

    por_sn = {(d.get('deviceSN') or '').upper(): d for d in lista}
    inversor_info = por_sn.get(sn)
    if not inversor_info:
        raise CadastroErro(f'Inversor {sn} não encontrado na conta FoxESS. Confira a SN.')

    id_usina = inversor_info.get('stationID')
    if not id_usina:
        raise CadastroErro(f'O inversor {sn} não está associado a nenhuma usina na FoxESS.')

    # 2) Dados da usina + todos os inversores dela (pela lista e pelos módulos da usina)
    try:
        usina_info = api.detalhe_usina(id_usina) or {}
    except FoxESSErro:
        usina_info = {}   # segue com o nome que veio na lista
    sns = {s for s, d in por_sn.items() if d.get('stationID') == id_usina}
    sns |= {(m.get('deviceSN') or '').upper() for m in usina_info.get('modules') or [] if m.get('deviceSN')}
    sns.add(sn)

    # Detalhe opcional (só para a potência nominal)
    capacidades = {}
    for numero in sorted(sns):
        try:
            capacidades[numero] = (api.detalhe_inversor(numero) or {}).get('capacity')
        except FoxESSErro:
            capacidades[numero] = None

    modelos = {n: _modelo_valido(por_sn.get(n, {}).get('deviceType')) for n in sns}
    status_inv = {n: STATUS_FOXESS.get(por_sn.get(n, {}).get('status'), Status.OFFLINE) for n in sns}
    conhecidos = [fabricante_pelo_modelo(m) for m in modelos.values() if m]
    fabricante = Counter(conhecidos).most_common(1)[0][0] if conhecidos else Fabricante.FOXESS

    # 3) Grava tudo de uma vez (ou nada)
    return _gravar(
        Plataforma.FOXESS, id_usina, cliente,
        usina={
            'nome': usina_info.get('stationName') or inversor_info.get('stationName') or f'Usina {sn}',
            'fabricante': fabricante,
            'endereco': usina_info.get('address') or '',
            'cidade': usina_info.get('city') or '',
            'fuso_horario': usina_info.get('timezone') or 'America/Sao_Paulo',
            'potencia_kwp': _decimal(usina_info.get('capacity')),
            'inicio_operacao': data_criacao_foxess(usina_info.get('createDate')),
            'status': status_da_usina(list(status_inv.values())),
        },
        inversores={n: {
            'id_externo': n,
            'modelo': modelos.get(n, ''),
            'potencia_nominal_kw': _decimal(capacidades.get(n)),
            'status': status_inv[n],
        } for n in sns},
    )


# Dados que a equipe pode corrigir no sistema: vêm da plataforma só no PRIMEIRO cadastro
CAMPOS_CADASTRAIS = {'nome', 'endereco', 'cidade', 'uf', 'latitude', 'longitude', 'potencia_kwp', 'fuso_horario',
                     'inicio_operacao'}


def _gravar(plataforma: str, id_usina: str, cliente: Usuario, usina: dict, inversores: dict[str, dict]) -> ResultadoCadastro:
    """
    Grava usina + inversores e vincula o cliente, numa transação. Reativa a usina se estava "apagada".
    Usina já existente: atualiza só o técnico (fabricante, status); os dados cadastrais editados
    pela equipe são mantidos.
    """
    estava_desativada = Usina.objects.filter(plataforma=plataforma, id_externo=id_usina, ativa=False).exists()
    tecnicos = {k: v for k, v in usina.items() if k not in CAMPOS_CADASTRAIS}
    with transaction.atomic():
        obj, nova = Usina.objects.update_or_create(
            plataforma=plataforma, id_externo=id_usina,
            defaults={**tecnicos, 'ativa': True, 'desativada_em': None},
            create_defaults={**usina, 'ativa': True, 'desativada_em': None},
        )
        if not obj.inicio_operacao and usina.get('inicio_operacao'):   # usina antiga ainda sem a data
            obj.inicio_operacao = usina['inicio_operacao']
            obj.save(update_fields=['inicio_operacao'])
        # Potência nominal já preenchida (pela plataforma ou pela equipe) não é sobrescrita
        com_potencia = set(Inversor.objects.filter(numero_serie__in=inversores, potencia_nominal_kw__gt=0)
                           .values_list('numero_serie', flat=True))
        for numero, dados in inversores.items():
            if numero in com_potencia:
                dados = {k: v for k, v in dados.items() if k != 'potencia_nominal_kw'}
            Inversor.objects.update_or_create(numero_serie=numero, defaults={'usina': obj, **dados})
        ja_vinculado = obj.usuarios.filter(pk=cliente.pk).exists()
        obj.usuarios.add(cliente)
    return ResultadoCadastro(usina=obj, usina_nova=nova, inversores=sorted(inversores),
                             ja_vinculado=ja_vinculado, reativada=estava_desativada)


# ----------------------------------------------------------------------------
# Huawei FusionSolar
# ----------------------------------------------------------------------------
STATUS_SAUDE_HUAWEI = {1: Status.OFFLINE, 2: Status.ALERTA, 3: Status.ONLINE}   # real_health_state


def potencia_pelo_modelo_huawei(modelo: str) -> Decimal:
    """'SUN2000L-3KTL' -> 3 · 'SUN2000-17KTL-M0' -> 17 · 'SUN2000-4.6KTL' -> 4.6 (kW nominal)."""
    achado = re.search(r'-(\d+(?:\.\d+)?)K', modelo or '', re.IGNORECASE)
    return _decimal(achado.group(1)) if achado else Decimal('0')


def _cadastrar_huawei(sn: str, cliente: Usuario) -> ResultadoCadastro:
    """
    A Huawei não busca dispositivo pela SN: lista as usinas da conta e os dispositivos delas
    (lotes de 100) até achar a SN. Com ~230 usinas são ~6 chamadas.
    """
    api = HuaweiCliente(settings.HUAWEI_API_URL, settings.HUAWEI_USUARIO, settings.HUAWEI_SENHA)
    try:
        usinas = {u['plantCode']: u for u in api.listar_usinas()}
        dispositivos = []
        codigos = list(usinas)
        for i in range(0, len(codigos), 100):
            lote = api.listar_dispositivos(codigos[i:i + 100])
            dispositivos += lote
            if any((d.get('esnCode') or '').upper() == sn for d in lote):
                break   # achou: não precisa listar o resto
    except HuaweiErro as erro:
        raise CadastroErro(f'Falha ao consultar a Huawei: {erro}') from erro

    achado = next((d for d in dispositivos if (d.get('esnCode') or '').upper() == sn), None)
    if not achado:
        raise CadastroErro(f'Inversor {sn} não encontrado na conta Huawei. Confira a SN.')
    if achado.get('devTypeId') not in TIPOS_INVERSOR:
        raise CadastroErro(f'A SN {sn} não é de um inversor (tipo {achado.get("devTypeId")}). Informe a SN do inversor.')

    codigo = achado['stationCode']
    info = usinas.get(codigo, {})
    inversores = [d for d in dispositivos if d.get('stationCode') == codigo and d.get('devTypeId') in TIPOS_INVERSOR]

    try:
        saude = (api.tempo_real_usinas([codigo]) or [{}])[0].get('dataItemMap', {}).get('real_health_state')
    except HuaweiErro:
        saude = None
    try:
        saude = int(float(saude)) if saude is not None else 0
    except (TypeError, ValueError):
        saude = 0
    status = STATUS_SAUDE_HUAWEI.get(saude, Status.OFFLINE)

    return _gravar(
        Plataforma.HUAWEI, codigo, cliente,
        usina={
            'nome': (info.get('plantName') or f'Usina {sn}').strip(),
            'fabricante': Fabricante.HUAWEI,
            'endereco': (info.get('plantAddress') or '').strip(),
            'latitude': _coordenada(info.get('latitude')),
            'longitude': _coordenada(info.get('longitude')),
            'potencia_kwp': _decimal(info.get('capacity')),   # confirmado: vem em kWp
            'inicio_operacao': data_conexao_huawei(info.get('gridConnectionDate')),
            'status': status,
        },
        inversores={(d.get('esnCode') or '').upper(): {
            'id_externo': str(d.get('id')),
            'tipo_externo': str(d.get('devTypeId')),
            'modelo': d.get('invType') or d.get('model') or '',
            'potencia_nominal_kw': potencia_pelo_modelo_huawei(d.get('invType') or d.get('model')),
            'status': status,
        } for d in inversores},
    )


# ----------------------------------------------------------------------------
# Sungrow iSolarCloud
# ----------------------------------------------------------------------------
def potencia_pelo_modelo_sungrow(modelo: str) -> Decimal:
    """'SG10RT' -> 10 · 'SG5.0RS' -> 5.0 · 'SG110CX' -> 110 · 'SH10RT' (híbrido) -> 10 (kW nominal)."""
    achado = re.match(r'S[GH]-?(\d+(?:\.\d+)?)', (modelo or '').strip(), re.IGNORECASE)
    return _decimal(achado.group(1)) if achado else Decimal('0')


def data_conexao_sungrow(valor) -> date | None:
    """grid_connection_time 20230303115625 ou install_date '2022-11-07 15:37:40' -> data."""
    texto = str(valor or '').strip()
    for formato, tamanho in (('%Y%m%d', 8), ('%Y-%m-%d', 10)):
        try:
            return _data_valida(datetime.strptime(texto[:tamanho], formato).date())
        except ValueError:
            continue
    return None


def _status_sungrow(dispositivo: dict) -> str:
    """Só para o 1º cadastro (a coleta de 5 min corrige): dev_fault_status 1 = falha; dev_status 1 = comunicando."""
    if str(dispositivo.get('dev_fault_status')) == '1':
        return Status.ALERTA
    return Status.ONLINE if str(dispositivo.get('dev_status')) == '1' else Status.OFFLINE


def _cadastrar_sungrow(sn: str, cliente: Usuario) -> ResultadoCadastro:
    """
    Acha a usina pela SN (getPowerStationDetail aceita a SN do inversor ou do comunicador). Se não achar,
    procura a SN no tempo real (inversor e, depois, híbrido) e pega o detalhe pelo ps_id.
    Depois lista os inversores da usina.
    """
    from .coleta_sungrow import PONTOS, fuso_sungrow

    try:
        api = SungrowCliente()
        try:
            info = api.detalhe_usina_por_sn(sn)
        except (SungrowLoginErro, SungrowLimiteErro):
            raise
        except SungrowErro:
            info = {}
        if not info.get('ps_id'):
            info = _usina_pelo_tempo_real(api, sn, PONTOS)
        if not info.get('ps_id'):
            raise CadastroErro(f'Inversor {sn} não encontrado na conta Sungrow. Confira a SN.')
        ps_id = info['ps_id']
        dispositivos = api.dispositivos_da_usina(ps_id)
    except SungrowLoginErro as erro:
        raise CadastroErro('Não foi possível entrar na conta Sungrow configurada no servidor. '
                           'Confira o usuário e a senha da Sungrow.') from erro
    except SungrowErro as erro:
        raise CadastroErro(f'Falha ao consultar a Sungrow: {erro}') from erro

    inversores = [d for d in dispositivos if int(_decimal(d.get('device_type'), 0)) in TIPOS_INVERSOR_SUNGROW
                  and d.get('device_sn') and d.get('ps_key')]
    if not inversores:
        raise CadastroErro(f'A usina do inversor {sn} não tem inversores na Sungrow.')
    status_inv = {d['device_sn'].upper(): _status_sungrow(d) for d in inversores}

    return _gravar(
        Plataforma.SUNGROW, str(ps_id), cliente,
        usina={
            'nome': (info.get('ps_name') or f'Usina {sn}').strip(),
            'fabricante': Fabricante.SUNGROW,
            'endereco': (info.get('ps_location') or '').strip()[:255],
            'latitude': _coordenada(info.get('latitude')),
            'longitude': _coordenada(info.get('longitude')),
            'fuso_horario': fuso_sungrow(info.get('ps_current_time_zone')),
            'potencia_kwp': _decimal(float(_decimal(info.get('design_capacity') or info.get('install_power'), 3))
                                     / 1000),   # vem em Wp
            'inicio_operacao': (data_conexao_sungrow(info.get('grid_connection_time'))
                                or data_conexao_sungrow(info.get('install_date'))),
            'status': status_da_usina(list(status_inv.values())),
        },
        inversores={d['device_sn'].upper(): {
            'id_externo': str(d['ps_key']),
            'tipo_externo': str(d.get('device_type')),
            'modelo': (d.get('device_model_code') or '').strip(),
            'potencia_nominal_kw': potencia_pelo_modelo_sungrow(d.get('device_model_code')),
            'status': status_inv[d['device_sn'].upper()],
        } for d in inversores},
    )


def _usina_pelo_tempo_real(api: SungrowCliente, sn: str, pontos: dict) -> dict:
    """SN no tempo real de inversores (e de híbridos) → ps_id → detalhe da usina. {} se não achar."""
    for tipo in TIPOS_INVERSOR_SUNGROW:
        try:
            itens = api.tempo_real_dispositivos(tipo, list(pontos[tipo]), sns=[sn])
        except (SungrowLoginErro, SungrowLimiteErro):
            raise
        except SungrowErro:
            continue          # SN não é deste tipo
        achado = next((d for d in itens if (d.get('device_sn') or '').upper() == sn and d.get('ps_id')), None)
        if achado:
            detalhes = api.detalhe_usinas([achado['ps_id']])
            return detalhes[0] if detalhes else {'ps_id': achado['ps_id']}
    return {}
