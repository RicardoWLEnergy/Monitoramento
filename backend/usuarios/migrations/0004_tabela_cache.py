"""
Cria a tabela "cache_sistema" (memória compartilhada usada para contar tentativas de login).
É o mesmo que rodar "manage.py createcachetable"; assim basta o "migrate" no servidor.
"""
from django.core.management import call_command
from django.db import migrations


def criar_tabela_cache(apps, schema_editor):
    call_command('createcachetable', verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ('usuarios', '0003_codigo_acesso'),
    ]

    operations = [
        migrations.RunPython(criar_tabela_cache, migrations.RunPython.noop),
    ]
