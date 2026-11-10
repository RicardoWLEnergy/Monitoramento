from rest_framework.routers import SimpleRouter

from .views import UsinaViewSet

router = SimpleRouter()
router.register('usinas', UsinaViewSet, basename='usina')

urlpatterns = router.urls
