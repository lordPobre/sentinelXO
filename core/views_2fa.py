"""
Sentinel XO — Autenticación de dos factores (TOTP)
Flujo: login → si 2FA activo → verificar código → acceso.
"""
import io
import base64
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse
from django.views.decorators.http import require_POST

logger = logging.getLogger("sentinel.2fa")


def totp_verify(request):
    """
    Muestra el formulario de verificación TOTP después del login.
    Solo se accede si el usuario está autenticado pero aún no pasó el 2FA.
    """
    if not request.user.is_authenticated:
        return redirect("login")

    # Si ya verificó en esta sesión, redirigir al dashboard
    if request.session.get("2fa_verified"):
        return redirect("dashboard:home")

    # Si el usuario no tiene 2FA activo, no necesita este paso
    try:
        totp_cfg = request.user.totp
        if not totp_cfg.is_enabled:
            request.session["2fa_verified"] = True
            return redirect(request.GET.get("next", "dashboard:home"))
    except Exception:
        request.session["2fa_verified"] = True
        return redirect(request.GET.get("next", "dashboard:home"))

    if request.method == "POST":
        code = request.POST.get("code", "").replace(" ", "")
        if totp_cfg.verify(code):
            request.session["2fa_verified"] = True
            totp_cfg.last_used = timezone.now()
            totp_cfg.save(update_fields=["last_used"])
            logger.info(f"2FA verificado para {request.user.username}")
            from core.models import AuditLog
            AuditLog.log(request=request, action="2fa_verified", resource="TOTP")
            return redirect(request.POST.get("next", "dashboard:home"))
        else:
            messages.error(request, "Código incorrecto. Inténtalo de nuevo.")
            logger.warning(f"2FA código inválido para {request.user.username}")

    return render(request, "2fa/verify.html", {
        "next": request.GET.get("next", "dashboard:home"),
    })


@login_required
def totp_setup(request):
    """Muestra el QR para configurar el 2FA por primera vez o regenerar el secreto."""
    import pyotp
    from core.models import UserTOTP

    totp_cfg, created = UserTOTP.objects.get_or_create(
        user=request.user,
        defaults={"secret": pyotp.random_base32()},
    )

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "regenerate":
            totp_cfg.secret = pyotp.random_base32()
            totp_cfg.is_enabled = False
            totp_cfg.save(update_fields=["secret", "is_enabled"])
            messages.success(request, "Secreto regenerado. Escanea el nuevo QR.")
            return redirect("totp-setup")

        if action == "enable":
            code = request.POST.get("code", "").replace(" ", "")
            if totp_cfg.verify(code):
                totp_cfg.is_enabled = True
                totp_cfg.save(update_fields=["is_enabled"])
                request.session["2fa_verified"] = True
                from core.models import AuditLog
                AuditLog.log(request=request, action="2fa_enabled", resource="TOTP")
                messages.success(request, "✅ Autenticación de dos factores activada correctamente.")
                logger.info(f"2FA activado para {request.user.username}")
                return redirect("dashboard:home")
            else:
                messages.error(request, "Código incorrecto. Verifica que tu app esté sincronizada.")

        if action == "disable":
            code = request.POST.get("code", "").replace(" ", "")
            if totp_cfg.verify(code):
                totp_cfg.is_enabled = False
                totp_cfg.save(update_fields=["is_enabled"])
                from core.models import AuditLog
                AuditLog.log(request=request, action="2fa_disabled", resource="TOTP")
                messages.success(request, "2FA desactivado.")
                logger.info(f"2FA desactivado para {request.user.username}")
                return redirect("totp-setup")
            else:
                messages.error(request, "Código incorrecto.")

    # Generar QR
    totp = pyotp.TOTP(totp_cfg.secret)
    company = "Sentinel XO"
    provision_url = totp.provisioning_uri(
        name=request.user.username,
        issuer_name=company,
    )

    try:
        import qrcode
        qr = qrcode.make(provision_url)
        buf = io.BytesIO()
        qr.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:
        qr_b64 = None

    return render(request, "2fa/setup.html", {
        "totp_cfg":      totp_cfg,
        "qr_b64":        qr_b64,
        "provision_url": provision_url,
        "secret_key":    totp_cfg.secret,
    })
