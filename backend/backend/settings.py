"""
Configurações do projeto Monitoramento (W.L Energy).

Valores sensíveis ou que mudam por ambiente (chave secreta, banco, hosts)
ficam no arquivo backend/.env, que NÃO vai para o git. Modelo: .env.example.
"""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / '.env')


# ---------- Segurança ----------
SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env.bool('DJANGO_DEBUG', default=False)
# A chave assina os logins (JWT): em produção, recusa iniciar com a chave de exemplo ou curta demais
if not DEBUG and (len(SECRET_KEY) < 40 or SECRET_KEY.startswith('gere-')):
    from django.core.exceptions import ImproperlyConfigured
    raise ImproperlyConfigured('DJANGO_SECRET_KEY de exemplo ou curta: gere uma chave nova (veja o README).')
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS', default=[])


# ---------- Aplicações ----------
INSTALLED_APPS = [
    # Django
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Terceiros
    'rest_framework',
    'corsheaders',
    # Projeto
    'usuarios',
    'usinas',
    'monitoramento',
    'integracoes',
]

# Usuário personalizado (login por e-mail + perfil). Precisa existir antes do 1º migrate.
AUTH_USER_MODEL = 'usuarios.Usuario'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',   # entrega /static/ (arquivos do /admin) em produção
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # precisa vir antes do CommonMiddleware
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'backend.wsgi.application'


# ---------- Banco de dados (PostgreSQL, via DATABASE_URL do .env) ----------
DATABASES = {
    'default': env.db('DATABASE_URL'),
}
# Mantém a conexão com o banco aberta por 60 s entre requisições (menos esforço do banco)
DATABASES['default']['CONN_MAX_AGE'] = 60

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------- Senhas ----------
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------- Idioma e fuso horário ----------
LANGUAGE_CODE = env('DJANGO_LANGUAGE_CODE', default='pt-br')
TIME_ZONE = env('DJANGO_TIME_ZONE', default='America/Sao_Paulo')
USE_I18N = True
USE_TZ = True  # grava em UTC no banco e converte para o fuso acima


# ---------- Arquivos estáticos ----------
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'   # onde o "collectstatic" junta os arquivos do /admin


# ---------- Produção (atrás do Caddy) ----------
# O Caddy recebe o HTTPS e repassa ao Django avisando "a conexão original era segura"
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Endereço público do sistema, ex.: https://monitoramento.wlenergy.com.br (ou https://IP)
CSRF_TRUSTED_ORIGINS = env.list('DJANGO_CSRF_TRUSTED_ORIGINS', default=[])
if not DEBUG:
    SESSION_COOKIE_SECURE = True    # cookies do /admin só trafegam por HTTPS
    CSRF_COOKIE_SECURE = True

# Erros aparecem no "docker compose logs" (sem isso, em produção ficariam invisíveis)
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'simples': {'format': '%(asctime)s %(levelname)s %(message)s', 'datefmt': '%d/%m %H:%M:%S'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'simples'}},
    'root': {'handlers': ['console'], 'level': 'WARNING'},
    'loggers': {'coletor': {'level': 'INFO'}},   # o coletor mostra cada ciclo (não só os erros)
}


# ---------- Monitoramento ----------
# Meses de curva detalhada (5 min) mantidos no banco. Os totais diários ficam para sempre.
LEITURAS_RETENCAO_MESES = env.int('LEITURAS_RETENCAO_MESES', default=13)


# ---------- Integrações (credenciais no .env) ----------
FOXESS_API_URL = env('FOXESS_API_URL', default='https://www.foxesscloud.com')
FOXESS_API_KEY = env('FOXESS_API_KEY', default='')
# Huawei: o host é o mesmo do portal web da empresa (ex.: la5, intl, eu5...) + /thirdData
HUAWEI_API_URL = env('HUAWEI_API_URL', default='https://la5.fusionsolar.huawei.com/thirdData')
HUAWEI_USUARIO = env('HUAWEI_USUARIO', default='')
HUAWEI_SENHA = env('HUAWEI_SENHA', default='')
# uazapi (WhatsApp): envio do código de acesso no login. URL = endereço do servidor no painel da uazapi
UAZAPI_URL = env('UAZAPI_URL', default='')
UAZAPI_TOKEN = env('UAZAPI_TOKEN', default='')   # token da INSTÂNCIA
# Clima (Open-Meteo): grátis só para uso NÃO comercial. Com o plano comercial, a chave vai aqui.
OPEN_METEO_CHAVE = env('OPEN_METEO_CHAVE', default='')
# Google (planilha OBRAS e documentos no Drive), com uma conta de serviço só de leitura.
# GOOGLE_CREDENCIAIS = conteúdo do arquivo JSON da chave, em base64 (ou o próprio JSON)
GOOGLE_CREDENCIAIS = env('GOOGLE_CREDENCIAIS', default='')
PLANILHA_OBRAS_ID = env('PLANILHA_OBRAS_ID', default='')   # o código no endereço: docs.google.com/spreadsheets/d/<ID>/
PLANILHA_OBRAS_ABA = env('PLANILHA_OBRAS_ABA', default='OBRAS')


# ---------- API (Django REST Framework + login JWT) ----------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],  # tudo exige login
    'DEFAULT_PAGINATION_CLASS': 'backend.paginacao.Paginacao',   # 20 por página; a tela pode pedir ?tamanho=
    'DEFAULT_FILTER_BACKENDS': ['rest_framework.filters.SearchFilter', 'rest_framework.filters.OrderingFilter'],
    'SEARCH_PARAM': 'busca',      # ?busca=texto
    'ORDERING_PARAM': 'ordem',    # ?ordem=nome  /  ?ordem=-potencia_kwp
    'COERCE_DECIMAL_TO_STRING': False,  # números como número no JSON (não como texto)
    # Limite de tentativas no login (por IP). Atrás do Caddy: 1 proxy → usa o IP real do visitante
    'NUM_PROXIES': 1,
    'DEFAULT_THROTTLE_RATES': {'login': '10/min', 'renovar': '30/min'},
}

# Memória compartilhada entre os atendentes do Gunicorn (contadores de tentativas de login).
# Fica numa tabela do banco, criada pela migração usuarios/0004.
CACHES = {
    'default': {'BACKEND': 'django.core.cache.backends.db.DatabaseCache', 'LOCATION': 'cache_sistema'},
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env.int('JWT_ACCESS_MINUTES', default=30)),
    # Validade máxima do login (a tela ainda encerra a sessão ao fechar o navegador)
    'REFRESH_TOKEN_LIFETIME': timedelta(hours=env.int('JWT_REFRESH_HOURS', default=12)),
    'UPDATE_LAST_LOGIN': True,
    # Trocar a senha derruba os logins abertos (o token guarda um resumo da senha)
    'CHECK_REVOKE_TOKEN': True,
}


# ---------- CORS (quem pode chamar a API pelo navegador) ----------
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
