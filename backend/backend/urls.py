"""
Rotas do projeto.

/admin/  → painel do Django (só perfil Admin)
/api/    → API usada pelo frontend Angular (exige login JWT, exceto /api/auth/login/)
"""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('usuarios.urls')),
    path('api/', include('usinas.urls')),
    path('api/', include('monitoramento.urls')),
]
