from django.urls import path
from rest_framework.routers import SimpleRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import EuView, LoginView, TrocarSenhaView, UsuarioViewSet

router = SimpleRouter()
router.register('usuarios', UsuarioViewSet, basename='usuario')

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/renovar/', TokenRefreshView.as_view(), name='renovar-token'),
    path('auth/eu/', EuView.as_view(), name='eu'),
    path('auth/trocar-senha/', TrocarSenhaView.as_view(), name='trocar-senha'),
    *router.urls,
]
