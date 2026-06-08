from django.urls import path
from . import views

app_name = "monitoring"

urlpatterns = [
    path("domains/", views.domain_list, name="domain-list"),
    path("domains/<int:domain_id>/refresh/", views.domain_refresh_htmx, name="domain-refresh"),
    path("clients/<uuid:client_id>/m365/sync/", views.m365_sync_htmx, name="m365-sync"),
]
