from django.urls import path
from . import views

app_name = "emailmon"

urlpatterns = [
    path("", views.m365_dashboard, name="dashboard"),
    path("m365/", views.m365_dashboard, name="m365-dashboard"),
    path("m365/check/", views.m365_check_now, name="m365-check"),
    path("test/send/", views.send_test, name="send-test"),
    path("webhook/brevo/", views.brevo_webhook, name="brevo-webhook"),
]
