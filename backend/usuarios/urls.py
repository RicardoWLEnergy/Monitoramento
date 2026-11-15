from django.urls import path
from rest_framework.routers import SimpleRouter
from .views import EntrarComCodigoView, EuView, LoginView, PedirCodigoView, RenovarView, TrocarSenhaView, UsuarioViewSet

router = SimpleRouter()
router.register('usuarios', UsuarioViewSet, basename='usuario')

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/renovar/', RenovarView.as_view(), name='renovar-token'),
    path('auth/codigo/', PedirCodigoView.as_view(), name='pedir-codigo'),
    path('auth/codigo/entrar/', EntrarComCodigoView.as_view(), name='entrar-com-codigo'),
    path('auth/eu/', EuView.as_view(), name='eu'),
    path('auth/trocar-senha/', TrocarSenhaView.as_view(), name='trocar-senha'),
    *router.urls,
]
