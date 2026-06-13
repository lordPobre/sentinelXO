"""
Sentinel XO — Signals para audit log automático.
"""
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    from core.models import AuditLog
    AuditLog.log(request=request, user=user, action="login",
                 resource="Panel web", success=True)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    from core.models import AuditLog
    AuditLog.log(request=request, user=user, action="logout",
                 resource="Panel web", success=True)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request, **kwargs):
    from core.models import AuditLog
    AuditLog.log(
        request=request, action="login",
        resource="Panel web",
        detail=f"Intento fallido para usuario: {credentials.get('username', '?')}",
        success=False,
    )
