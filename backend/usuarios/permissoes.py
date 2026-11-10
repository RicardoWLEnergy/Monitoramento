"""
Regras de acesso por perfil — num só lugar.

- Admin:       tudo.
- Colaborador: vê todas as usinas; cadastra clientes e vincula usinas; NÃO altera alertas.
- Cliente:     só vê as usinas vinculadas a ele.
"""
from rest_framework.permissions import BasePermission

from .models import Usuario

ADMIN = Usuario.Perfil.ADMIN
COLABORADOR = Usuario.Perfil.COLABORADOR
CLIENTE = Usuario.Perfil.CLIENTE


def perfil_de(usuario) -> str | None:
    return getattr(usuario, 'perfil', None) if usuario and usuario.is_authenticated else None


def e_equipe(usuario) -> bool:
    """Admin ou Colaborador (equipe da WL)."""
    return perfil_de(usuario) in (ADMIN, COLABORADOR)


class EhAdmin(BasePermission):
    message = 'Apenas administradores podem fazer isso.'

    def has_permission(self, request, view):
        return perfil_de(request.user) == ADMIN


class EhEquipe(BasePermission):
    message = 'Apenas a equipe WL (Admin ou Colaborador) pode fazer isso.'

    def has_permission(self, request, view):
        return e_equipe(request.user)


def usinas_visiveis(usuario):
    """Usinas ATIVAS que o usuário pode ver: todas para a equipe; só as vinculadas para o cliente."""
    from usinas.models import Usina
    if e_equipe(usuario):
        return Usina.objects.ativas()
    return Usina.objects.ativas().filter(usuarios=usuario)
