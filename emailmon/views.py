import json
import hmac
import hashlib
import logging
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Q
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from core.models import Client
from .services import check_m365_graph_health
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, HttpResponseNotAllowed
from django.conf import settings
from .models import EmailLog, SmtpCheck
from core.models import MaintenanceIncident

logger = logging.getLogger("perseus")

BREVO_EVENT_MAP = {
    "delivered":          "sent",
    "hard_bounce":        "bounced",
    "soft_bounce":        "bounced",
    "blocked":            "failed",
    "spam":               "bounced",
    "invalid_email":      "failed",
    "error":              "failed",
    "unsubscribed":       "sent",   
    "click":              "sent",
    "open":               "sent",
    "complaint":          "bounced",
    "deferred":           "failed",
}


@csrf_exempt
@require_POST
def brevo_webhook(request):
    """
    POST /email/webhook/brevo/
    Recibe eventos de Brevo y actualiza EmailLog automáticamente.

    Configurar en Brevo:
      Transactional → Webhooks → Add a new webhook
      URL: https://tu-dominio.com/email/webhook/brevo/
      Eventos: delivered, hard_bounce, soft_bounce, blocked, spam, error, invalid_email
    """
    secret = getattr(settings, "BREVO_WEBHOOK_SECRET", "")
    if secret:
        signature = request.headers.get("X-Brevo-Signature", "")
        expected = hmac.new(
            secret.encode(),
            request.body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("Webhook Brevo: firma inválida")
            return HttpResponseForbidden("Firma inválida")

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON inválido")

    events = payload if isinstance(payload, list) else [payload]

    updated = 0
    created = 0

    for event in events:
        event_type = event.get("event", "")
        recipient  = event.get("email", "")
        message_id = event.get("message-id", "") or event.get("messageId", "")
        reason     = event.get("reason", "") or event.get("description", "")
        ts         = event.get("ts_epoch") or event.get("date")

        if not recipient or not event_type:
            continue

        new_status = BREVO_EVENT_MAP.get(event_type)
        if not new_status:
            logger.debug(f"Webhook Brevo: evento ignorado '{event_type}'")
            continue

        logger.info(f"Webhook Brevo: {event_type} → {recipient} (status: {new_status})")

        log = (
            EmailLog.objects
            .filter(recipient__iexact=recipient)
            .order_by("-sent_at")
            .first()
        )

        if log:
            priority = {"sent": 1, "failed": 2, "bounced": 3}
            current_prio = priority.get(log.status, 0)
            new_prio     = priority.get(new_status, 0)

            if new_prio >= current_prio:
                log.status    = new_status
                log.error_msg = reason[:500] if reason else log.error_msg
                log.save(update_fields=["status", "error_msg"])
                updated += 1
                logger.info(f"EmailLog actualizado: {recipient} → {new_status}")
        else:
            EmailLog.objects.create(
                recipient=recipient,
                subject=f"[Brevo webhook] {event_type}",
                category="other",
                status=new_status,
                error_msg=reason[:500] if reason else "",
            )
            created += 1
            logger.info(f"EmailLog creado desde webhook: {recipient} → {new_status}")

        if new_status in ("bounced", "failed") and event_type in ("hard_bounce", "blocked", "invalid_email", "error"):
            
            if not MaintenanceIncident.objects.filter(
                title__icontains=recipient,
                is_resolved=False,
            ).exists():
                MaintenanceIncident.objects.create(
                    client=log.client if log else None,
                    title=f"Email no entregado a {recipient}",
                    description=(
                        f"Brevo reportó evento '{event_type}' para {recipient}.\n"
                        f"Razón: {reason or 'Sin detalle'}\n"
                        f"Tipo: {event_type}"
                    ),
                    severity="medium",
                )
                logger.warning(f"Incidente creado por bounce: {recipient}")

    return HttpResponse(
        json.dumps({"processed": len(events), "updated": updated, "created": created}),
        content_type="application/json",
        status=200,
    )


@login_required
def m365_check_now(request):
    """
    POST /email/m365/check/
    Ejecuta verificación M365 en tiempo real usando Graph API (sin SMTP).
    """
    if not request.user.is_staff:
        
        return HttpResponseForbidden()

    if request.method != "POST":
        
        return HttpResponseNotAllowed(["POST"])

    client_id = request.POST.get("client_id")
    client    = None
    if client_id:
        try:
            client = Client.objects.get(pk=client_id)
        except Client.DoesNotExist:
            pass

    if not client:
        clients = Client.objects.filter(is_active=True, m365_tenant__is_active=True)
        results = []
        for c in clients:
            r = check_m365_graph_health(c)
            results.append(r)
        result = {
            "client":  "Global",
            "overall": "ok" if all(r["overall"] == "ok" for r in results) else "warning",
            "results": results,
            "errors":  [],
        }
    else:
        result = check_m365_graph_health(client)

    return render(request, "emailmon/partials/m365_status.html", {"result": result})


@login_required
def send_test(request):
    """
    POST /email/test/send/
    Envía un email de prueba (vía Resend) al correo del usuario o al indicado.
    Devuelve un fragmento HTML con el resultado para mostrar en el dashboard.
    """
    if not request.user.is_staff:
        return HttpResponseForbidden()

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    from .services import send_test_email
    to = request.POST.get("email") or request.user.email
    if not to:
        return HttpResponse(
            '<div style="font-size:12px;color:#f87171;">'
            'No hay un email de destino. Configura tu correo en tu perfil.</div>'
        )

    result = send_test_email(to)
    if result.get("success"):
        return HttpResponse(
            f'<div style="font-size:12px;color:#10b981;">'
            f'✓ Email de prueba enviado a {to}. Revisa tu bandeja.</div>'
        )
    else:
        err = result.get("error", "error desconocido")
        return HttpResponse(
            f'<div style="font-size:12px;color:#f87171;word-break:break-word;">'
            f'✗ Falló el envío: {err}</div>'
        )


def m365_dashboard(request):
    """Panel de monitoreo M365 — muestra estado SMTP y Graph API por cliente."""
    if not request.user.is_staff:
        return redirect("dashboard:home")

    m365_clients = Client.objects.filter(
        is_active=True,
        m365_tenant__is_active=True,
    ).prefetch_related("m365_licenses", "m365_tenant")

    
    since_24h = timezone.now() - timezone.timedelta(hours=24)

    M365_HOST = "graph.microsoft.com (M365)"
    graph_qs  = SmtpCheck.objects.filter(
        smtp_host=M365_HOST,
        checked_at__gte=since_24h,
    )
    total  = graph_qs.count()
    ok     = graph_qs.filter(status="ok").count()
    uptime = round((ok / total * 100), 1) if total > 0 else None
    latest = SmtpCheck.objects.filter(
        smtp_host=M365_HOST,
    ).order_by("-checked_at").first()

    m365_checks = SmtpCheck.objects.filter(
        smtp_host=M365_HOST,
    ).order_by("-checked_at")[:24]

    chart_checks = list(SmtpCheck.objects.filter(
        smtp_host=M365_HOST,
    ).order_by("-checked_at")[:48])
    chart_checks.reverse()
    chart_data = {
        "labels": [timezone.localtime(c.checked_at).strftime("%H:%M") for c in chart_checks],
        "ms":     [c.response_ms or 0 for c in chart_checks],
        "status": [c.status for c in chart_checks],
    }

    checks_with_details = graph_qs.exclude(check_details={})
    send_total = checks_with_details.count()
    send_ok    = sum(1 for c in checks_with_details
                     if c.check_details.get("send_status") == "ok")
    recv_ok    = sum(1 for c in checks_with_details
                     if c.check_details.get("recv_status") == "ok")

    send_pct = round(send_ok / send_total * 100, 1) if send_total > 0 else None
    recv_pct = round(recv_ok / send_total * 100, 1) if send_total > 0 else None

    last_with_details = graph_qs.exclude(check_details={}).order_by("-checked_at").first()
    last_send = last_with_details.check_details.get("send_status") if last_with_details else None
    last_recv = last_with_details.check_details.get("recv_status") if last_with_details else None
    last_recv_detail = last_with_details.check_details.get("last_recv", "") if last_with_details else ""

    return render(request, "emailmon/m365_dashboard.html", {
        "m365_clients":     m365_clients,
        "m365_checks":      m365_checks,
        "uptime":           uptime,
        "latest":           latest,
        "chart_data_json":  json.dumps(chart_data),
        "section":          "email",
        "via_graph":        True,
        "send_pct":         send_pct,
        "recv_pct":         recv_pct,
        "last_send":        last_send,
        "last_recv":        last_recv,
        "last_recv_detail": last_recv_detail,
    })
