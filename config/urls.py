from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from apps.portal.metrics import prometheus_metrics, readiness_probe


def healthz(_request):
    return JsonResponse({"status": "ok", "service": "bd-grievance-platform"})


urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("readyz/", readiness_probe, name="readyz"),
    path("metrics", prometheus_metrics, name="prometheus-metrics"),
    path("admin/", admin.site.urls),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/accounts/", include("apps.accounts.urls")),
    path("api/v1/complaints/", include("apps.complaints.urls")),
    path("api/v1/organogram/", include("apps.organogram.urls")),
    path("api/v1/workflow/", include("apps.workflow.urls")),
    path("api/v1/ai-triage/", include("apps.ai_triage.urls")),
    path("api/v1/disaster/", include("apps.disaster.urls")),
    path("api/v1/esb/", include("apps.esb.urls")),
    path("", include("apps.portal.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
