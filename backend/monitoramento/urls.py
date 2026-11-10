from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import AlertaViewSet, DashboardView

router = SimpleRouter()
router.register('alertas', AlertaViewSet, basename='alerta')

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    *router.urls,
]
