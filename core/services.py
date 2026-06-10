"""
Servicios de monitoreo de email:
  - check_smtp_connectivity(): verifica que el servidor SMTP responde
  - send_tracked_email(): wrapper de send_mail que registra el resultado
  - send_test_email(): envía un email de prueba verificable
"""
import smtplib
import socket
import time
import logging
from django.conf import settings
from django.core.mail import EmailMessage
from .models import EmailLog, SmtpCheck

logger = logging.getLogger("perseus")


def check_smtp_connectivity() -> SmtpCheck:
    """
    Intenta conectarse al servidor SMTP y mide el tiempo de respuesta.
    No envía ningún email — solo verifica que el puerto responde.
    """
    host = getattr(settings, "EMAIL_HOST", "smtp-relay.brevo.com")
    port = getattr(settings, "EMAIL_PORT", 587)
    timeout = 10

    start = time.monotonic()
    try:
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            # Intentar STARTTLS si está disponible
            if smtp.has_extn("STARTTLS"):
                smtp.starttls()
                smtp.ehlo()
        elapsed_ms = int((time.monotonic() - start) * 1000)
        check = SmtpCheck.objects.create(
            status="ok",
            response_ms=elapsed_ms,
            smtp_host=host,
            smtp_port=port,
        )
        logger.info(f"SMTP check OK: {host}:{port} — {elapsed_ms}ms")

    except (socket.timeout, TimeoutError):
        elapsed_ms = int((time.monotonic() - start) * 1000)
        check = SmtpCheck.objects.create(
            status="timeout",
            response_ms=elapsed_ms,
            smtp_host=host,
            smtp_port=port,
            error_msg=f"Timeout después de {timeout}s",
        )
        logger.warning(f"SMTP timeout: {host}:{port}")
        # Disparar alerta inteligente
        try:
            from core.alert_engine import evaluate_smtp_failure
            from core.models import Client
            for client in Client.objects.filter(is_active=True):
                evaluate_smtp_failure(client, f"{host}:{port}", f"Timeout después de {timeout}s")
        except Exception as _ae:
            pass

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        check = SmtpCheck.objects.create(
            status="error",
            response_ms=elapsed_ms,
            smtp_host=host,
            smtp_port=port,
            error_msg=str(e)[:500],
        )
        logger.error(f"SMTP error: {host}:{port} — {e}")
        # Disparar alerta inteligente
        try:
            from core.alert_engine import evaluate_smtp_failure
            from core.models import Client
            for client in Client.objects.filter(is_active=True):
                evaluate_smtp_failure(client, f"{host}:{port}", str(e)[:200])
        except Exception as _ae:
            pass

    return check


def send_tracked_email(
    subject: str,
    body: str,
    to: list[str],
    category: str = "other",
    client=None,
    attachments: list = None,
) -> bool:
    """
    Envía un email y registra el resultado en EmailLog.
    Retorna True si se envió correctamente.
    """
    success = True
    error_msg = ""

    try:
        email = EmailMessage(
            subject=subject,
            body=body,
            to=to,
        )
        if attachments:
            for filename, content, mimetype in attachments:
                email.attach(filename, content, mimetype)
        email.send()
        logger.info(f"Email enviado → {', '.join(to)} | {subject[:60]}")

    except Exception as e:
        success = False
        error_msg = str(e)[:500]
        logger.error(f"Error enviando email → {', '.join(to)}: {e}")

    # Registrar cada destinatario por separado
    for recipient in to:
        EmailLog.objects.create(
            recipient=recipient,
            subject=subject,
            category=category,
            status="sent" if success else "failed",
            error_msg=error_msg,
            client=client,
        )

    return success


def send_test_email(to: str) -> dict:
    """
    Envía un email de prueba y retorna el resultado completo.
    Usado desde el panel de administrador.
    """
    from django.utils import timezone

    # 1. Verificar SMTP primero
    check = check_smtp_connectivity()

    if check.status != "ok":
        return {
            "success": False,
            "smtp_status": check.status,
            "smtp_ms": check.response_ms,
            "error": check.error_msg,
        }

    # 2. Enviar email de prueba
    subject = f"[Sentinel XO] Email de prueba — {timezone.now().strftime('%d/%m/%Y %H:%M')}"
    body = (
        f"Este es un email de prueba del sistema Sentinel XO.\n\n"
        f"Servidor SMTP: {check.smtp_host}:{check.smtp_port}\n"
        f"Tiempo de respuesta: {check.response_ms}ms\n"
        f"Generado: {timezone.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"Si recibes este mensaje, el sistema de email está funcionando correctamente."
    )

    success = send_tracked_email(subject, body, [to], category="test")

    return {
        "success": success,
        "smtp_status": check.status,
        "smtp_ms": check.response_ms,
        "error": "" if success else "Error al enviar",
    }


# ─── Verificación SMTP Microsoft 365 ─────────────────────────────────────────

M365_SMTP_HOST = "smtp.office365.com"
M365_SMTP_PORT = 587
M365_IMAP_HOST = "outlook.office365.com"
M365_IMAP_PORT = 993


def check_m365_smtp(client=None) -> dict:
    """
    Verifica conectividad SMTP de Microsoft 365.
    No envía emails — solo verifica que el servidor responde y negocia TLS.
    Retorna dict con: status, smtp_ms, graph_ms, error, details
    """
    import smtplib
    import ssl
    import socket
    import time
    from .models import SmtpCheck

    results = {
        "client":   str(client) if client else "Global",
        "smtp":     None,
        "graph":    None,
        "overall":  "ok",
        "errors":   [],
    }

    # ── 1. Verificar SMTP smtp.office365.com:587 ──────────────────────────────
    start = time.monotonic()
    try:
        with smtplib.SMTP(M365_SMTP_HOST, M365_SMTP_PORT, timeout=10) as smtp:
            smtp.ehlo()
            # Verificar que STARTTLS está disponible (obligatorio en M365)
            if smtp.has_extn("STARTTLS"):
                smtp.starttls()
                smtp.ehlo()
                tls_ok = True
            else:
                tls_ok = False
                results["errors"].append("STARTTLS no disponible")

        smtp_ms = int((time.monotonic() - start) * 1000)
        results["smtp"] = {
            "host":       M365_SMTP_HOST,
            "port":       M365_SMTP_PORT,
            "status":     "ok",
            "ms":         smtp_ms,
            "tls":        tls_ok,
        }
        logger.info(f"M365 SMTP OK: {M365_SMTP_HOST}:{M365_SMTP_PORT} — {smtp_ms}ms")

        # Guardar en SmtpCheck con el host de M365
        SmtpCheck.objects.create(
            status="ok",
            response_ms=smtp_ms,
            smtp_host=M365_SMTP_HOST,
            smtp_port=M365_SMTP_PORT,
        )

    except (socket.timeout, TimeoutError):
        smtp_ms = int((time.monotonic() - start) * 1000)
        results["smtp"] = {"host": M365_SMTP_HOST, "port": M365_SMTP_PORT,
                           "status": "timeout", "ms": smtp_ms}
        results["overall"] = "warning"
        results["errors"].append(f"SMTP timeout ({smtp_ms}ms)")
        SmtpCheck.objects.create(status="timeout", response_ms=smtp_ms,
                                  smtp_host=M365_SMTP_HOST, smtp_port=M365_SMTP_PORT,
                                  error_msg="Timeout")
        logger.warning(f"M365 SMTP timeout: {M365_SMTP_HOST}:{M365_SMTP_PORT}")

    except Exception as e:
        smtp_ms = int((time.monotonic() - start) * 1000)
        results["smtp"] = {"host": M365_SMTP_HOST, "port": M365_SMTP_PORT,
                           "status": "error", "ms": smtp_ms, "error": str(e)}
        results["overall"] = "error"
        results["errors"].append(f"SMTP error: {e}")
        SmtpCheck.objects.create(status="error", response_ms=smtp_ms,
                                  smtp_host=M365_SMTP_HOST, smtp_port=M365_SMTP_PORT,
                                  error_msg=str(e)[:500])
        logger.error(f"M365 SMTP error: {e}")

    # ── 2. Verificar Graph API (si el cliente tiene tenant configurado) ────────
    if client and hasattr(client, "m365_tenant") and client.m365_tenant.is_active:
        tenant = client.m365_tenant  # definir antes del try para que el except lo vea
        start = time.monotonic()
        try:
            import requests as req_lib
            from monitoring.services import get_graph_token
            token  = get_graph_token(
                tenant.tenant_id,
                tenant.azure_client_id,
                tenant.azure_client_secret,
            )
            # Llamada ligera — solo el perfil de la organización
            resp = req_lib.get(
                "https://graph.microsoft.com/v1.0/organization",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            graph_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                org = resp.json().get("value", [{}])[0]
                results["graph"] = {
                    "status":        "ok",
                    "ms":            graph_ms,
                    "tenant_name":   org.get("displayName", "—"),
                    "verified_domains": [
                        d["name"] for d in org.get("verifiedDomains", [])
                        if d.get("isDefault")
                    ],
                }
                logger.info(f"M365 Graph OK: {client} — {graph_ms}ms")
            else:
                results["graph"] = {"status": "error", "ms": graph_ms,
                                    "error": f"HTTP {resp.status_code}"}
                results["overall"] = "warning"
                results["errors"].append(f"Graph API HTTP {resp.status_code}")

        except Exception as e:
            graph_ms = int((time.monotonic() - start) * 1000)
            results["graph"] = {"status": "error", "ms": graph_ms, "error": str(e)}
            if results["overall"] == "ok":
                results["overall"] = "warning"
            results["errors"].append(f"Graph API error: {e}")
            logger.warning(f"M365 Graph error para {client}: {e}")
    else:
        results["graph"] = {"status": "not_configured"}

    return results
