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


# ---------- API (Django REST Framework + login JWT) ----------
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],  # tudo exige login
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': ['rest_framework.filters.SearchFilter', 'rest_framework.filters.OrderingFilter'],
    'SEARCH_PARAM': 'busca',      # ?busca=texto
    'ORDERING_PARAM': 'ordem',    # ?ordem=nome  /  ?ordem=-potencia_kwp
    'COERCE_DECIMAL_TO_STRING': False,  # números como número no JSON (não como texto)
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=env.int('JWT_ACCESS_MINUTES', default=30)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=env.int('JWT_REFRESH_DAYS', default=7)),
    'UPDATE_LAST_LOGIN': True,
}


# ---------- CORS (quem pode chamar a API pelo navegador) ----------
CORS_ALLOWED_ORIGINS = env.list('CORS_ALLOWED_ORIGINS', default=[])
