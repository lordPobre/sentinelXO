from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("",                                        views.home,                  name="home"),
    # Admin Perseus
    path("admin/overview/",                         views.admin_overview,        name="admin-overview"),
    path("admin/clients/",                          views.admin_clients,         name="admin-clients"),
    path("admin/clients/<uuid:client_id>/",         views.admin_client_detail,   name="admin-client-detail"),
    # Portal cliente
    path("select/",                                 views.client_select,         name="client-select"),
    path("portal/<uuid:client_id>/",                views.client_portal,         name="client-portal"),
    path("realtime/<uuid:client_id>/",              views.realtime_dashboard,    name="realtime"),
    # Detalle de dispositivo en tiempo real
    path("device/<uuid:device_id>/",                views.device_detail_live,    name="device-live"),
    # HTMX fragments
    path("htmx/devices/<uuid:device_id>/",          views.htmx_device_detail,    name="htmx-device-detail"),
    path("htmx/clients/<uuid:client_id>/incidents/create/",
                                                    views.htmx_incident_create,  name="htmx-incident-create"),
    path("htmx/incidents/<int:incident_id>/resolve/",
                                                    views.htmx_incident_resolve, name="htmx-incident-resolve"),
]
