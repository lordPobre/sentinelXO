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
                is_healthy  = svc_status in ("serviceOperational", "serviceRestored")
                is_degraded = "Degradation" in svc_status or "degradation" in svc_status
                is_incident = "Incident" in svc_status or "incident" in svc_status

                if is_healthy:
                    chk_status = "ok"
                elif is_degraded:
                    chk_status = "warning"  # degradación = advertencia, no error
                else:
                    chk_status = "error"

                result["checks"]["exchange_health"] = {
                    "status":     chk_status,
                    "ms":         health_ms,
                    "label":      "Estado Exchange Online",
                    "svc_status": svc_status,
                    "detail":     exchange.get("statusDisplayName", svc_status),
                }
                if not is_healthy:
                    # Solo escalar a error si hay incidente, degradación es solo warning
                    result["overall"] = "error" if is_incident else "warning"
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

    # ── 5. Envío real — sendMail vía Graph API ────────────────────────────────
    # Requiere permiso Mail.Send en la app Azure
    # Solo envía email de verificación si el cliente no tiene notify_incidents_only
    start = time.monotonic()
    try:
        # Enviar a todos los emails de alerta configurados en el cliente
        alert_recipients = client.get_alert_recipients()
        # Respetar preferencia notify_incidents_only — no enviar email de verificación
        if getattr(client, "notify_incidents_only", False):
            test_recipient = ""
        else:
            test_recipient = alert_recipients[0] if alert_recipients else (client.contact_email or "")
        if test_recipient:
            company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
            from django.utils import timezone as tz
            mail_payload = {
                "message": {
                    "subject": f"[{company}] Check de conectividad SMTP — {tz.now().strftime('%H:%M')}",
                    "body": {
                        "contentType": "Text",
                        "content": (
                            "Este es un email de verificacion automatica enviado por " + company + "\n\n"
                            "Si recibes este mensaje, el envio de correo desde M365 funciona correctamente.\n"
                            "Hora del check: " + tz.now().strftime("%d/%m/%Y %H:%M:%S") + "\n\n"
                            "(No es necesario responder este mensaje)"
                        ),
                    },
                    "toRecipients": [{"emailAddress": {"address": test_recipient}}],
                },
                "saveToSentItems": "false",
            }
            # Necesitamos un usuario desde el cual enviar — usamos el primero con licencia
            users_resp = req_lib.get(
                "https://graph.microsoft.com/v1.0/users?$filter=assignedLicenses/$count ne 0"
                "&$count=true&$select=id,mail&$top=1",
                headers={**headers, "ConsistencyLevel": "eventual"},
                timeout=10,
            )
            sender_id = None
            if users_resp.status_code == 200:
                users_val = users_resp.json().get("value", [])
                if users_val:
                    sender_id = users_val[0].get("id")

            if sender_id:
                send_resp = req_lib.post(
                    f"https://graph.microsoft.com/v1.0/users/{sender_id}/sendMail",
                    headers={**headers, "Content-Type": "application/json"},
                    json=mail_payload,
                    timeout=15,
                )
                send_ms = int((time.monotonic() - start) * 1000)
                if send_resp.status_code == 202:
                    result["checks"]["smtp_send"] = {
                        "status": "ok", "ms": send_ms,
                        "label":  "Envío SMTP (sendMail)",
                        "detail": f"Email enviado a {test_recipient}",
                    }
                    logger.info(f"M365 sendMail OK para {client} → {test_recipient} ({send_ms}ms)")
                elif send_resp.status_code == 403:
                    result["checks"]["smtp_send"] = {
                        "status": "skipped", "ms": send_ms,
                        "label":  "Envío SMTP (sendMail)",
                        "detail": "Sin permiso Mail.Send — añadir en Azure App Registration",
                    }
                else:
                    err_detail = send_resp.json().get("error", {}).get("message", f"HTTP {send_resp.status_code}")
                    result["checks"]["smtp_send"] = {
                        "status": "error", "ms": send_ms,
                        "label":  "Envío SMTP (sendMail)",
                        "error":  err_detail[:150],
                    }
                    if result["overall"] == "ok":
                        result["overall"] = "warning"
                    result["errors"].append(f"sendMail: {err_detail[:100]}")
            else:
                result["checks"]["smtp_send"] = {
                    "status": "skipped", "ms": 0,
                    "label":  "Envío SMTP (sendMail)",
                    "detail": "Sin usuarios con licencia encontrados",
                }
        else:
            result["checks"]["smtp_send"] = {
                "status": "skipped", "ms": 0,
                "label":  "Envío SMTP (sendMail)",
                "detail": "Sin email de contacto configurado para el cliente",
            }
    except Exception as e:
        result["checks"]["smtp_send"] = {
            "status": "error", "ms": 0,
            "label":  "Envío SMTP (sendMail)",
            "error":  str(e)[:150],
        }
        logger.error(f"M365 sendMail error para {client}: {e}")

    # ── 6. Recepción real — leer últimos mensajes del buzón ───────────────────
    # Requiere permiso Mail.ReadBasic.All en la app Azure
    start = time.monotonic()
    try:
        # Obtener el primer usuario con licencia
        users_resp = req_lib.get(
            "https://graph.microsoft.com/v1.0/users?$filter=assignedLicenses/$count ne 0"
            "&$count=true&$select=id,mail,displayName&$top=1",
            headers={**headers, "ConsistencyLevel": "eventual"},
            timeout=10,
        )
        recv_ms = int((time.monotonic() - start) * 1000)

        if users_resp.status_code == 200:
            users_val = users_resp.json().get("value", [])
            if users_val:
                user_id    = users_val[0].get("id")
                user_email = users_val[0].get("mail", "—")
                # Leer los últimos 5 emails recibidos
                msgs_resp = req_lib.get(
                    f"https://graph.microsoft.com/v1.0/users/{user_id}/messages"
                    "?$select=receivedDateTime,subject&$top=5&$orderby=receivedDateTime desc",
                    headers=headers,
                    timeout=10,
                )
                recv_ms = int((time.monotonic() - start) * 1000)
                if msgs_resp.status_code == 200:
                    messages  = msgs_resp.json().get("value", [])
                    last_recv = messages[0].get("receivedDateTime", "") if messages else None
                    # Parsear fecha del último email recibido
                    last_recv_str = "—"
                    hours_ago     = None
                    if last_recv:
                        try:
                            from datetime import datetime, timezone as dt_tz
                            dt = datetime.fromisoformat(last_recv.replace("Z", "+00:00"))
                            from django.utils import timezone as dj_tz
                            hours_ago = (dj_tz.now() - dt).total_seconds() / 3600
                            last_recv_str = dt.strftime("%d/%m %H:%M")
                        except Exception:
                            last_recv_str = last_recv[:16]

                    result["checks"]["smtp_recv"] = {
                        "status":    "ok", "ms": recv_ms,
                        "label":     "Recepción SMTP (buzón)",
                        "detail":    f"{len(messages)} emails · último: {last_recv_str}",
                        "mailbox":   user_email,
                        "msg_count": len(messages),
                        "hours_ago": hours_ago,
                    }
                    logger.info(f"M365 recepción OK para {client}: {len(messages)} msgs, último {last_recv_str}")
                elif msgs_resp.status_code == 403:
                    result["checks"]["smtp_recv"] = {
                        "status": "skipped", "ms": recv_ms,
                        "label":  "Recepción SMTP (buzón)",
                        "detail": "Sin permiso Mail.ReadBasic.All — añadir en Azure App Registration",
                    }
                else:
                    result["checks"]["smtp_recv"] = {
                        "status": "error", "ms": recv_ms,
                        "label":  "Recepción SMTP (buzón)",
                        "error":  f"HTTP {msgs_resp.status_code}",
                    }
            else:
                result["checks"]["smtp_recv"] = {
                    "status": "skipped", "ms": recv_ms,
                    "label":  "Recepción SMTP (buzón)",
                    "detail": "Sin usuarios con licencia",
                }
        else:
            result["checks"]["smtp_recv"] = {
                "status": "skipped", "ms": recv_ms,
                "label":  "Recepción SMTP (buzón)",
                "detail": f"HTTP {users_resp.status_code}",
            }
    except Exception as e:
        result["checks"]["smtp_recv"] = {
            "status": "error", "ms": 0,
            "label":  "Recepción SMTP (buzón)",
            "error":  str(e)[:150],
        }
        logger.error(f"M365 recepción error para {client}: {e}")

    # Registrar en SmtpCheck para el historial
    overall_ok = result["overall"] == "ok"
    best_ms = min(
        (v.get("ms", 0) for v in result["checks"].values() if v.get("ms")),
        default=0
    )
    err_summary  = "; ".join(result["errors"])[:500] if result["errors"] else ""
    overall_str  = result["overall"]
    # "warning" = degradación de servicio MS — no es un fallo nuestro, guardar como "ok"
    smtpcheck_status = "ok" if overall_str in ("ok", "warning") else "error"
    if overall_str == "warning":
        logger.warning(f"M365 advertencia para {client}: {err_summary}")
    elif overall_str == "error":
        logger.error(f"M365 check fallido para {client}: {err_summary}")

    # Guardar detalle de envío y recepción para el KPI
    send_check = result["checks"].get("smtp_send", {})
    recv_check = result["checks"].get("smtp_recv", {})
    SmtpCheck.objects.create(
        status=smtpcheck_status,
        response_ms=best_ms,
        smtp_host="graph.microsoft.com (M365)",
        smtp_port=443,
        error_msg=err_summary,
        check_details={
            "send_status": send_check.get("status", "skipped"),
            "send_ms":     send_check.get("ms", 0),
            "recv_status": recv_check.get("status", "skipped"),
            "recv_ms":     recv_check.get("ms", 0),
            "recv_count":  recv_check.get("msg_count", 0),
            "last_recv":   recv_check.get("detail", ""),
        },
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
