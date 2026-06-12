from django.urls import path
from . import views
from core import views_alerts as alerts_views
from core import views_security as security_views

app_name = "dashboard"

urlpatterns = [
    path("",                                        views.home,                  name="home"),
    # Admin Sentinel XO
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

    # Alertas
    path("alerts/",                                     alerts_views.alerts_dashboard,   name="alerts"),
    path("alerts/rules/create/",                        alerts_views.alert_rule_create,  name="alert-rule-create"),
    path("alerts/rules/<int:rule_id>/toggle/",          alerts_views.alert_rule_toggle,  name="alert-rule-toggle"),
    path("alerts/rules/<int:rule_id>/delete/",          alerts_views.alert_rule_delete,  name="alert-rule-delete"),
    path("alerts/events/<int:event_id>/resolve/",       alerts_views.alert_event_resolve, name="alert-event-resolve"),
    path("alerts/events/<int:event_id>/silence/",       alerts_views.alert_event_silence, name="alert-event-silence"),

    # Seguridad
    path("security/",                                   security_views.security_dashboard, name="security"),
    path("security/<uuid:client_id>/check/",            security_views.security_check_now, name="security-check"),
    path("security/<uuid:client_id>/analyze/",          security_views.security_ai_analysis, name="security-ai-analysis"),
]
