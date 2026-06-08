from django.contrib import admin
from django.http import JsonResponse
from django.utils import timezone


def health_check(request):
    """Health check endpoint para Railway."""
    return JsonResponse({"status": "ok", "time": timezone.now().isoformat()})
from django.urls import path, include
from django.views.generic import RedirectView

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(url="/dashboard/", permanent=False)),
    path("auth/", include("django.contrib.auth.urls")),
    path("dashboard/", include("dashboard.urls", namespace="dashboard")),
    path("monitoring/", include("monitoring.urls", namespace="monitoring")),
    path("reports/", include("reports.urls", namespace="reports")),
    path("api/v1/", include("core.api_urls", namespace="api")),
    path("email/", include("emailmon.urls", namespace="emailmon")),
]
