"""
Sentinel XO — Servicios de Email
Usa la API HTTP de Brevo (sin SMTP) — compatible con Railway plan Hobby.
"""
import time
import logging
import urllib.request
import urllib.error
import json
import socket
from django.conf import settings
from .models import EmailLog, SmtpCheck

logger = logging.getLogger("perseus")


# ── Brevo API HTTP ─────────────────────────────────────────────────────────────

def _resend_send(subject: str, body: str, to: list[str],
                 attachments: list = None) -> tuple[bool, str]:
    """
    Envía un email vía API HTTP de Resend.
    No usa SMTP — funciona en Railway plan Hobby.
    Retorna (success, error_msg).
    """
    api_key      = getattr(settings, "RESEND_API_KEY", "")
    sender_email = getattr(settings, "DEFAULT_FROM_EMAIL", "soporte@perseustechnology.dev")
    sender_name  = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")

    if not api_key:
        return False, "RESEND_API_KEY no configurada en variables de entorno"

    payload = {
        "from":    f"{sender_name} <{sender_email}>",
        "to":      to,
        "subject": subject,
        "text":    body,
    }

    if attachments:
        payload["attachments"] = []
        import base64
        for filename, file_content, mimetype in attachments:
            if isinstance(file_content, bytes):
                b64 = base64.b64encode(file_content).decode()
            else:
                b64 = base64.b64encode(file_content.encode()).decode()
            payload["attachments"].append({
                "filename": filename,
                "content":  b64,
            })

    try:
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(
            "https://api.resend.com/emails",
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            msg_id = result.get("id", "—")
            logger.info(f"Resend OK → {', '.join(to)} | id={msg_id}")
            return True, ""

    except urllib.error.HTTPError as e:
        body_err = e.read().decode(errors="ignore")[:300]
        logger.error(f"Resend HTTP {e.code}: {body_err}")
        return False, f"Resend error {e.code}: {body_err}"
    except Exception as e:
        logger.error(f"Resend error: {e}")
        return False, str(e)[:300]


def check_resend_api() -> SmtpCheck:
    """
    Verifica conectividad con la API de Resend.
    Hace un GET al endpoint de dominios — si responde, la API está OK.
    """
    api_key = getattr(settings, "RESEND_API_KEY", "")
    start   = time.monotonic()

    try:
        req = urllib.request.Request(
            "https://api.resend.com/domains",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            json.loads(resp.read().decode())
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(f"Resend API OK — {elapsed_ms}ms")
            return SmtpCheck.objects.create(
                status="ok",
                response_ms=elapsed_ms,
                smtp_host="api.resend.com",
                smtp_port=443,
            )

    except urllib.error.HTTPError as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        err = f"HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}"
        logger.error(f"Resend API error: {err}")
        check = SmtpCheck.objects.create(
            status="error",
            response_ms=elapsed_ms,
            smtp_host="api.resend.com",
            smtp_port=443,
            error_msg=err,
        )
        _fire_smtp_alert(err)
        return check

    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.error(f"Resend API no disponible: {e}")
        check = SmtpCheck.objects.create(
            status="error",
            response_ms=elapsed_ms,
            smtp_host="api.resend.com",
            smtp_port=443,
            error_msg=str(e)[:500],
        )
        _fire_smtp_alert(str(e)[:200])
        return check


def _fire_smtp_alert(error_msg: str):
    """Dispara alerta inteligente cuando la API de email falla."""
    try:
        from core.alert_engine import evaluate_smtp_failure
        from core.models import Client
        for client in Client.objects.filter(is_active=True):
            evaluate_smtp_failure(client, "api.resend.com:443", error_msg)
    except Exception as ae:
        logger.debug(f"Alert engine: {ae}")


# Alias para compatibilidad con código que llama check_smtp_connectivity
def check_smtp_connectivity() -> SmtpCheck:
    return check_resend_api()


# ── send_tracked_email ────────────────────────────────────────────────────────

def send_tracked_email(
    subject: str,
    body: str,
    to: list[str],
    category: str = "other",
    client=None,
    attachments: list = None,
) -> bool:
    """
    Envía un email vía Brevo API y registra el resultado en EmailLog.
    Retorna True si se envió correctamente.
    """
    success, error_msg = _resend_send(subject, body, to, attachments)

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
    """Envía un email de prueba y retorna el resultado."""
    from django.utils import timezone

    # Verificar API antes de enviar
    check = check_resend_api()

    subject = f"[Sentinel XO] Email de prueba — {timezone.now().strftime('%d/%m/%Y %H:%M')}"
    body = (
        f"Este es un email de prueba del sistema Sentinel XO.\n\n"
        f"Canal: Resend API HTTP (sin SMTP)\n"
        f"Tiempo de respuesta API: {check.response_ms}ms\n"
        f"Generado: {timezone.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        f"Si recibes este mensaje, el sistema de email está funcionando correctamente."
    )

    success = send_tracked_email(subject, body, [to], category="test")

    return {
        "success":     success,
        "smtp_status": check.status,
        "smtp_ms":     check.response_ms,
        "error":       "" if success else "Error al enviar — revisa RESEND_API_KEY",
    }




def check_m365_graph_health(client) -> dict:
    """
    Monitorea el estado del servicio de email de Microsoft 365 usando Graph API.
    No usa SMTP (puerto 587) — funciona en Railway plan Hobby.

    Verifica 3 cosas vía HTTPS:
      1. Token válido  → credenciales Azure correctas
      2. Exchange Online health → estado oficial del servicio M365
      3. Buzones activos → que el tenant tiene usuarios con email
    """
    import time
    import requests as req_lib
    from monitoring.services import get_graph_token

    result = {
        "client":   str(client),
        "overall":  "ok",
        "errors":   [],
        "checks":   {},
    }

    if not (hasattr(client, "m365_tenant") and client.m365_tenant and client.m365_tenant.is_active):
        return {**result, "overall": "not_configured",
                "errors": ["Tenant M365 no configurado para este cliente"]}

    tenant = client.m365_tenant

    # ── 1. Obtener token (valida credenciales Azure) ───────────────────────────
    start = time.monotonic()
    try:
        token = get_graph_token(
            tenant.tenant_id,
            tenant.azure_client_id,
            tenant.azure_client_secret,
        )
        token_ms = int((time.monotonic() - start) * 1000)
        result["checks"]["auth"] = {"status": "ok", "ms": token_ms,
                                     "label": "Autenticación Azure AD"}
    except Exception as e:
        err_str = str(e)
        logger.error(f"M365 Auth error para {client}: {err_str}")
        result["checks"]["auth"] = {"status": "error", "ms": 0,
                                     "label": "Autenticación Azure AD",
                                     "error": err_str[:200]}
        result["overall"] = "error"
        result["errors"].append(f"Auth fallida: {err_str[:200]}")
        return result  # sin token no podemos continuar

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    # ── 2. Service Health — estado de Exchange Online ─────────────────────────
    # Requiere permiso ServiceHealth.Read.All en la app Azure
    start = time.monotonic()
    try:
        resp = req_lib.get(
            "https://graph.microsoft.com/v1.0/admin/serviceAnnouncement/healthOverviews",
            headers=headers, timeout=10,
        )
        health_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            services = resp.json().get("value", [])
            exchange = next(
                (s for s in services if "Exchange" in s.get("service", "")), None
            )
            if exchange:
                svc_status = exchange.get("status", "unknown")
                is_healthy = svc_status in ("serviceOperational", "serviceRestored")
                result["checks"]["exchange_health"] = {
                    "status":     "ok" if is_healthy else "warning",
                    "ms":         health_ms,
                    "label":      "Estado Exchange Online",
                    "svc_status": svc_status,
                    "detail":     exchange.get("statusDisplayName", svc_status),
                }
                if not is_healthy:
                    result["overall"] = "warning"
                    result["errors"].append(f"Exchange Online: {svc_status}")
            else:
                # Endpoint OK pero sin datos de Exchange — permiso insuficiente
                result["checks"]["exchange_health"] = {
                    "status": "skipped", "ms": health_ms,
                    "label":  "Estado Exchange Online",
                    "detail": "Permiso ServiceHealth.Read.All no configurado en Azure App",
                }
        elif resp.status_code == 403:
            result["checks"]["exchange_health"] = {
                "status": "skipped", "ms": health_ms,
                "label":  "Estado Exchange Online",
                "detail": "Sin permiso ServiceHealth.Read.All — añadir en Azure App Registration",
            }
        else:
            result["checks"]["exchange_health"] = {
                "status": "error", "ms": health_ms,
                "label":  "Estado Exchange Online",
                "error":  f"HTTP {resp.status_code}",
            }
            result["overall"] = "warning"

    except Exception as e:
        result["checks"]["exchange_health"] = {
            "status": "error", "ms": 0,
            "label":  "Estado Exchange Online",
            "error":  str(e)[:150],
        }
        result["overall"] = "warning"
        result["errors"].append(f"Service Health error: {e}")

    # ── 3. Verificar que hay usuarios con buzón (mailbox activo) ───────────────
    start = time.monotonic()
    try:
        resp = req_lib.get(
            "https://graph.microsoft.com/v1.0/users?$select=displayName,mail,assignedLicenses"
            "&$filter=assignedLicenses/$count ne 0&$count=true&$top=1",
            headers={**headers, "ConsistencyLevel": "eventual"},
            timeout=10,
        )
        users_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code == 200:
            data       = resp.json()
            user_count = data.get("@odata.count", len(data.get("value", [])))
            result["checks"]["mailboxes"] = {
                "status": "ok", "ms": users_ms,
                "label":  "Buzones activos",
                "count":  user_count,
                "detail": f"{user_count} usuario(s) con licencia",
            }
        else:
            result["checks"]["mailboxes"] = {
                "status": "skipped", "ms": users_ms,
                "label":  "Buzones activos",
                "detail": f"HTTP {resp.status_code} — sin permiso User.Read.All",
            }
    except Exception as e:
        result["checks"]["mailboxes"] = {
            "status": "error", "ms": 0,
            "label":  "Buzones activos",
            "error":  str(e)[:150],
        }

    # ── 4. Ping ligero a Graph (latencia general M365) ────────────────────────
    start = time.monotonic()
    try:
        resp = req_lib.get(
            "https://graph.microsoft.com/v1.0/organization",
            headers=headers, timeout=10,
        )
        ping_ms = int((time.monotonic() - start) * 1000)
        if resp.status_code == 200:
            org = resp.json().get("value", [{}])[0]
            result["checks"]["graph_ping"] = {
                "status":      "ok", "ms": ping_ms,
                "label":       "Graph API latencia",
                "tenant_name": org.get("displayName", "—"),
            }
        else:
            result["checks"]["graph_ping"] = {
                "status": "error", "ms": ping_ms,
                "label":  "Graph API latencia",
                "error":  f"HTTP {resp.status_code}",
            }
    except Exception as e:
        result["checks"]["graph_ping"] = {
            "status": "error", "ms": 0,
            "label":  "Graph API latencia",
            "error":  str(e)[:150],
        }

    # Registrar en SmtpCheck para el historial
    overall_ok = result["overall"] == "ok"
    best_ms = min(
        (v.get("ms", 0) for v in result["checks"].values() if v.get("ms")),
        default=0
    )
    err_summary = "; ".join(result["errors"])[:500] if result["errors"] else ""
    if err_summary:
        logger.error(f"M365 check fallido para {client}: {err_summary}")
    SmtpCheck.objects.create(
        status="ok" if overall_ok else "error",
        response_ms=best_ms,
        smtp_host="graph.microsoft.com (M365)",
        smtp_port=443,
        error_msg=err_summary,
    )

    return result

# ── check_m365_smtp (solo verifica Graph API, no SMTP) ───────────────────────

M365_SMTP_HOST = "smtp.office365.com"
M365_SMTP_PORT = 587


def check_m365_smtp(client=None) -> dict:
    """
    Verifica Microsoft 365 vía Graph API.
    El check SMTP a office365.com se omite en Railway (puerto bloqueado).
    """
    results = {
        "client":  str(client) if client else "Global",
        "smtp":    {"host": M365_SMTP_HOST, "port": M365_SMTP_PORT,
                    "status": "skipped", "ms": 0,
                    "note": "Puerto 587 no disponible en Railway — usando Graph API"},
        "graph":   None,
        "overall": "ok",
        "errors":  [],
    }

    # Verificar Graph API si el cliente tiene tenant
    if client and hasattr(client, "m365_tenant") and client.m365_tenant.is_active:
        tenant = client.m365_tenant
        start  = time.monotonic()
        try:
            import requests as req_lib
            from monitoring.services import get_graph_token
            token    = get_graph_token(
                tenant.tenant_id,
                tenant.azure_client_id,
                tenant.azure_client_secret,
            )
            resp     = req_lib.get(
                "https://graph.microsoft.com/v1.0/organization",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            graph_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code == 200:
                org = resp.json().get("value", [{}])[0]
                results["graph"] = {
                    "status":           "ok",
                    "ms":               graph_ms,
                    "tenant_name":      org.get("displayName", "—"),
                    "verified_domains": [
                        d["name"] for d in org.get("verifiedDomains", [])
                        if d.get("isDefault")
                    ],
                }
                logger.info(f"M365 Graph OK: {client} — {graph_ms}ms")
            else:
                results["graph"]   = {"status": "error", "ms": graph_ms,
                                       "error": f"HTTP {resp.status_code}"}
                results["overall"] = "warning"
                results["errors"].append(f"Graph API HTTP {resp.status_code}")

        except Exception as e:
            graph_ms = int((time.monotonic() - start) * 1000)
            results["graph"]   = {"status": "error", "ms": graph_ms, "error": str(e)}
            results["overall"] = "warning"
            results["errors"].append(f"Graph API error: {e}")
            logger.warning(f"M365 Graph error {client}: {e}")
    else:
        results["graph"] = {"status": "not_configured"}

    return results
