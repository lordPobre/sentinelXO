from django.urls import path
from .views_api import (
    TelemetryIngestView,
    DeviceHistoryView,
    DeviceStatusView,
    DeviceLiveView,
    ClientLiveSummaryView,
)
from .views_ai import device_ai_analysis, incident_ai_diagnosis

app_name = "api"

urlpatterns = [
    path("telemetry/",                             TelemetryIngestView.as_view(),   name="telemetry-ingest"),
    path("devices/<str:token>/status/",            DeviceStatusView.as_view(),      name="device-status"),
    path("devices/<uuid:device_id>/live/",         DeviceLiveView.as_view(),        name="device-live"),
    path("clients/<uuid:client_id>/live/",         ClientLiveSummaryView.as_view(), name="client-live"),
    path("devices/<uuid:device_id>/history/",      DeviceHistoryView.as_view(),     name="device-history"),
    path("devices/<uuid:device_id>/ai-analysis/",  device_ai_analysis,              name="device-ai-analysis"),
    path("incidents/<int:incident_id>/diagnosis/",     incident_ai_diagnosis,           name="incident-ai-diagnosis"),
]
