from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AlertaViewSet, DashboardCurvaView, DashboardGeracaoDiariaView, DashboardView

router = SimpleRouter()
router.register('alertas', AlertaViewSet, basename='alerta')

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('dashboard/curva/', DashboardCurvaView.as_view(), name='dashboard-curva'),
    path('dashboard/geracao-diaria/', DashboardGeracaoDiariaView.as_view(), name='dashboard-geracao-diaria'),
    *router.urls,
]
