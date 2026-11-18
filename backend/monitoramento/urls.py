from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import (
    AlertaViewSet, DashboardCurvaView, DashboardGeracaoDiariaView, DashboardView, DocumentoProjetoView, ProjetoView,
)

router = SimpleRouter()
router.register('alertas', AlertaViewSet, basename='alerta')

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('dashboard/curva/', DashboardCurvaView.as_view(), name='dashboard-curva'),
    path('dashboard/geracao-diaria/', DashboardGeracaoDiariaView.as_view(), name='dashboard-geracao-diaria'),
    path('projeto/', ProjetoView.as_view(), name='projeto'),
    path('projeto/documentos/<str:tipo>/', DocumentoProjetoView.as_view(), name='projeto-documento'),
    *router.urls,
]
