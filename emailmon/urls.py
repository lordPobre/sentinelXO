from django.urls import path
from . import views

app_name = "emailmon"

urlpatterns = [
    # La raíz de /email/ ahora muestra el dashboard M365 (el SMTP fue eliminado)
    path("", views.m365_dashboard, name="dashboard"),
    path("m365/", views.m365_dashboard, name="m365-dashboard"),
    path("m365/check/", views.m365_check_now, name="m365-check"),
    path("webhook/brevo/", views.brevo_webhook, name="brevo-webhook"),
]
