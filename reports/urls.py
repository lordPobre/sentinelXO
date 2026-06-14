from django.urls import path
from . import views

app_name = "reports"

urlpatterns = [
    path("", views.report_list, name="list"),
    path("<int:report_id>/download/", views.report_download, name="download"),
    path("generate/<uuid:client_id>/", views.report_generate_now, name="generate-now"),
    # Reporte individual por dispositivo
    path("device/<uuid:device_id>/", views.device_report_download, name="device-report"),
    # Reporte de postura de seguridad
    path("security/<uuid:client_id>/", views.security_report_download, name="security-report"),
    # Documento de producto: funcionamiento y arquitectura del sistema
    path("sistema/", views.system_overview_download, name="system-overview"),
]
