import json
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, Q
from .models import EmailLog, SmtpCheck
from .services import send_test_email, check_smtp_connectivity


@login_required
def email_dashboard(request):
    """Panel principal de monitoreo de email."""
    if not request.user.is_staff:
        return redirect("dashboard:home")

    # Estadísticas de las últimas 24h
    since_24h = timezone.now() - timezone.timedelta(hours=24)
    since_7d  = timezone.now() - timezone.timedelta(days=7)

    logs_24h   = EmailLog.objects.filter(sent_at__gte=since_24h)
    sent_24h   = logs_24h.filter(status="sent").count()
    failed_24h = logs_24h.filter(status="failed").count()

    logs_7d    = EmailLog.objects.filter(sent_at__gte=since_7d)
    sent_7d    = logs_7d.filter(status="sent").count()
    failed_7d  = logs_7d.filter(status="failed").count()

    # Último check SMTP
    latest_check = SmtpCheck.objects.first()

    # Uptime SMTP últimas 24h (% de checks OK)
    checks_24h = SmtpCheck.objects.filter(checked_at__gte=since_24h)
    total_checks = checks_24h.count()
    ok_checks    = checks_24h.filter(status="ok").count()
    smtp_uptime  = round((ok_checks / total_checks * 100), 1) if total_checks > 0 else None

    # Logs recientes
    recent_logs   = EmailLog.objects.select_related("client")[:50]
    recent_checks = SmtpCheck.objects.all()[:24]

    # Checks SMTP para gráfico (últimas 24 verificaciones)
    chart_checks = list(SmtpCheck.objects.order_by("-checked_at")[:48])
    chart_checks.reverse()
    chart_data = {
        "labels": [c.checked_at.strftime("%H:%M") for c in chart_checks],
        "ms":     [c.response_ms or 0 for c in chart_checks],
        "status": [c.status for c in chart_checks],
    }

    context = {
        "sent_24h":     sent_24h,
        "failed_24h":   failed_24h,
        "sent_7d":      sent_7d,
        "failed_7d":    failed_7d,
        "latest_check": latest_check,
        "smtp_uptime":  smtp_uptime,
        "recent_logs":  recent_logs,
        "recent_checks": recent_checks,
        "chart_data_json": json.dumps(chart_data),
        "section": "email",
    }
    return render(request, "emailmon/dashboard.html", context)


@login_required
def smtp_check_now(request):
    """HTMX: ejecuta un check SMTP en tiempo real y devuelve el resultado."""
    if not request.user.is_staff:
        return JsonResponse({"error": "Sin acceso"}, status=403)

    if request.method == "POST":
        check = check_smtp_connectivity()
        return render(request, "emailmon/partials/smtp_status.html", {"check": check})

    return JsonResponse({"error": "Método no permitido"}, status=405)


@login_required
def send_test(request):
    """Envía un email de prueba al email del usuario logueado."""
    if not request.user.is_staff:
        return redirect("dashboard:home")

    if request.method == "POST":
        to = request.POST.get("email", request.user.email)
        if not to:
            messages.error(request, "Ingresa un email de destino.")
            return redirect("emailmon:dashboard")

        result = send_test_email(to)
        if result["success"]:
            messages.success(request, f"Email de prueba enviado a {to} — SMTP {result['smtp_ms']}ms")
        else:
            messages.error(request, f"Error: {result['error']} (SMTP: {result['smtp_status']})")

    return redirect("emailmon:dashboard")


@login_required
def live_status(request):
    """
    GET /email/live/
    HTMX polling cada 10s — devuelve el fragmento completo de estado en tiempo real.
    Ejecuta un check SMTP automáticamente si el último tiene más de 1 hora.
    """
    if not request.user.is_staff:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    from django.utils import timezone
    from .services import check_resend_api

    # Auto-check API cada 5 min
    latest_check = SmtpCheck.objects.filter(
        smtp_host__icontains="resend"
    ).order_by("-checked_at").first()
    five_min_ago = timezone.now() - timezone.timedelta(minutes=5)
    if not latest_check or latest_check.checked_at < five_min_ago:
        latest_check = check_resend_api()

    since_24h = timezone.now() - timezone.timedelta(hours=24)

    checks_24h    = SmtpCheck.objects.filter(checked_at__gte=since_24h)
    total_checks  = checks_24h.count()
    ok_checks     = checks_24h.filter(status="ok").count()
    smtp_uptime   = round((ok_checks / total_checks * 100), 1) if total_checks > 0 else None

    logs_24h      = EmailLog.objects.filter(sent_at__gte=since_24h)
    sent_24h      = logs_24h.filter(status="sent").count()
    failed_24h    = logs_24h.filter(status="failed").count()
    recent_logs   = EmailLog.objects.select_related("client")[:20]
    recent_checks = SmtpCheck.objects.all()[:12]

    return render(request, "emailmon/partials/live_panel.html", {
        "latest_check":  latest_check,
        "smtp_uptime":   smtp_uptime,
        "sent_24h":      sent_24h,
        "failed_24h":    failed_24h,
        "recent_logs":   recent_logs,
        "recent_checks": recent_checks,
        "now":           timezone.now(),
    })


import json
import hmac
import hashlib
import logging
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.conf import settings

logger = logging.getLogger("perseus")

# Mapeo de eventos Brevo → estado en EmailLog
BREVO_EVENT_MAP = {
    # Entrega exitosa
    "delivered":          "sent",
    # Problemas — marcar como rebotado o fallido
    "hard_bounce":        "bounced",
    "soft_bounce":        "bounced",
    "blocked":            "failed",
    "spam":               "bounced",
    "invalid_email":      "failed",
    "error":              "failed",
    "unsubscribed":       "sent",   # entregado pero el usuario se desinscribió
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
    # 1. Verificar firma si hay secret configurado
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

    # 2. Parsear payload
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponseBadRequest("JSON inválido")

    # Brevo puede enviar un array o un objeto único
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

        # 3. Buscar el EmailLog más reciente para este destinatario
        log = (
            EmailLog.objects
            .filter(recipient__iexact=recipient)
            .order_by("-sent_at")
            .first()
        )

        if log:
            # Actualizar solo si el nuevo estado es peor o diferente
            # (no queremos sobreescribir 'bounced' con 'sent' si llegan fuera de orden)
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
            # No existe el log — crear uno (email enviado fuera del sistema)
            EmailLog.objects.create(
                recipient=recipient,
                subject=f"[Brevo webhook] {event_type}",
                category="other",
                status=new_status,
                error_msg=reason[:500] if reason else "",
            )
            created += 1
            logger.info(f"EmailLog creado desde webhook: {recipient} → {new_status}")

        # 4. Si es bounce o error grave, crear incidente automático
        if new_status in ("bounced", "failed") and event_type in ("hard_bounce", "blocked", "invalid_email", "error"):
            from core.models import MaintenanceIncident
            # Solo crear si no hay uno abierto para este email
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
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    if request.method != "POST":
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(["POST"])

    from core.models import Client
    from .services import check_m365_graph_health

    client_id = request.POST.get("client_id")
    client    = None
    if client_id:
        try:
            client = Client.objects.get(pk=client_id)
        except Client.DoesNotExist:
            pass

    if not client:
        # Verificar todos los clientes con M365 configurado
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


def m365_dashboard(request):
    """Panel de monitoreo M365 — muestra estado SMTP y Graph API por cliente."""
    if not request.user.is_staff:
        return redirect("dashboard:home")

    from core.models import Client
    from django.utils import timezone

    # Clientes con M365 configurado
    m365_clients = Client.objects.filter(
        is_active=True,
        m365_tenant__is_active=True,
    ).prefetch_related("m365_licenses", "m365_tenant")

    from .models import SmtpCheck
    import json
    since_24h = timezone.now() - timezone.timedelta(hours=24)

    # Checks via Graph API (nuevo método, sin SMTP)
    graph_qs  = SmtpCheck.objects.filter(
        smtp_host__icontains="graph.microsoft.com",
        checked_at__gte=since_24h,
    )
    total  = graph_qs.count()
    ok     = graph_qs.filter(status="ok").count()
    uptime = round((ok / total * 100), 1) if total > 0 else None
    latest = SmtpCheck.objects.filter(
        smtp_host__icontains="graph.microsoft.com"
    ).order_by("-checked_at").first()

    # Si no hay checks Graph aún, mostrar el más reciente de cualquier tipo
    if not latest:
        latest = SmtpCheck.objects.order_by("-checked_at").first()

    # Historial para la tabla (Graph API + cualquier check reciente)
    m365_checks = SmtpCheck.objects.filter(
        smtp_host__icontains="graph.microsoft.com"
    ).order_by("-checked_at")[:24]

    # Gráfico — últimos 48 checks Graph API
    chart_checks = list(SmtpCheck.objects.filter(
        smtp_host__icontains="graph.microsoft.com"
    ).order_by("-checked_at")[:48])
    chart_checks.reverse()
    chart_data = {
        "labels": [c.checked_at.strftime("%H:%M") for c in chart_checks],
        "ms":     [c.response_ms or 0 for c in chart_checks],
        "status": [c.status for c in chart_checks],
    }

    return render(request, "emailmon/m365_dashboard.html", {
        "m365_clients":    m365_clients,
        "m365_checks":     m365_checks,
        "uptime":          uptime,
        "latest":          latest,
        "chart_data_json": json.dumps(chart_data),
        "section":         "email",
        "via_graph":       True,
    })
