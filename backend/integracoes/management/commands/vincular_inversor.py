"""
Cadastra a usina de um inversor (pela SN) e vincula ao cliente.
Teste do fluxo que depois será usado pela tela de cadastro do sistema.

Uso:
    python manage.py vincular_inversor cliente@email.com J0VB753048DG212 --plataforma foxess
"""
from django.core.management.base import BaseCommand, CommandError

from integracoes.cadastro import CadastroErro, cadastrar_por_sn
from usinas.models import Plataforma
from usuarios.models import Usuario


class Command(BaseCommand):
    help = 'Cadastra a usina de um inversor (SN) e vincula ao cliente informado.'

    def add_arguments(self, parser):
        parser.add_argument('email', help='E-mail do cliente (já cadastrado, perfil Cliente).')
        parser.add_argument('sn', help='Número de série (SN) do inversor.')
        parser.add_argument('--plataforma', required=True, choices=Plataforma.values)

    def handle(self, *args, **opcoes):
        try:
            cliente = Usuario.objects.get(email=opcoes['email'].strip().lower())
        except Usuario.DoesNotExist:
            raise CommandError(f"Cliente {opcoes['email']} não existe. Cadastre-o antes (ex.: pelo /admin).")

        try:
            r = cadastrar_por_sn(opcoes['plataforma'], opcoes['sn'], cliente)
        except (CadastroErro, ValueError) as erro:
            raise CommandError(str(erro)) from erro

        u = r.usina
        self.stdout.write(self.style.SUCCESS(
            f"Usina {'cadastrada' if r.usina_nova else 'já existia (dados atualizados)'}: {u.nome}"))
        self.stdout.write(f'  Plataforma: {u.get_plataforma_display()}  |  Fabricante: {u.get_fabricante_display()}')
        self.stdout.write(f'  Potência: {u.potencia_kwp} kWp  |  Status: {u.get_status_display()}  |  Fuso: {u.fuso_horario}')
        self.stdout.write(f"  Endereço: {', '.join(p for p in (u.endereco, u.cidade) if p) or '—'}")
        self.stdout.write(f'  Mapa: {u.link_maps or "—"}')
        self.stdout.write(f"  Inversores ({len(r.inversores)}): {', '.join(r.inversores)}")
        self.stdout.write(
            f'  Cliente {cliente.nome}: ' + ('já estava vinculado.' if r.ja_vinculado else 'vinculado agora.'))
