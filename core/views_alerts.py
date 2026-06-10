"""
Sentinel XO — Vistas del sistema de alertas
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import AlertRule, AlertEvent, Client, HardwareDevice


@login_required
def alerts_dashboard(request):
    """Vista principal del panel de alertas."""
    # Verificar que las tablas existen (pueden no existir si la migración no se aplicó)
    try:
        from django.db import connection
        tables = connection.introspection.table_names()
        if "core_alertrule" not in tables or "core_alertevent" not in tables:
            return render(request, "core/alerts_dashboard.html", {
                "section": "alerts",
                "events": [], "rules": [], "all_events": [],
                "clients": [], "devices": [],
                "firing_critical": 0, "firing_warning": 0,
                "resolved_today": 0, "total_rules": 0,
                "METRIC_CHOICES": AlertRule.METRIC_CHOICES,
                "SEVERITY_CHOICES": AlertRule.SEVERITY_CHOICES,
                "migration_pending": True,
            })
    except Exception:
        pass

    # Staff ve todos los clientes, cliente ve solo el suyo
    if request.user.is_staff:
        clients       = Client.objects.filter(is_active=True).prefetch_related("devices")
        events_qs     = AlertEvent.objects.filter(status="firing").select_related(
            "device", "device__client", "rule").order_by("-fired_at")
        rules         = AlertRule.objects.filter(is_active=True).select_related(
            "client", "device").order_by("client", "metric")
        all_events    = AlertEvent.objects.select_related(
            "device", "device__client").order_by("-fired_at")[:100]
    else:
        portal = request.user.client_portals.first()
        if not portal:
            from django.http import Http404
            raise Http404
        clients       = Client.objects.filter(pk=portal.pk)
        events_qs     = AlertEvent.objects.filter(
            device__client=portal, status="firing").select_related(
            "device", "rule").order_by("-fired_at")
        rules         = AlertRule.objects.filter(
            client=portal, is_active=True).select_related("device").order_by("metric")
        all_events    = AlertEvent.objects.filter(
            device__client=portal).select_related("device").order_by("-fired_at")[:100]

    # Contadores ANTES del slice
    firing_critical = events_qs.filter(severity="critical").count()
    firing_warning  = events_qs.filter(severity="warning").count()
    resolved_today  = AlertEvent.objects.filter(
        status="resolved",
        resolved_at__date=timezone.now().date(),
    ).count()

    # Slice para el template
    events = events_qs[:50]

    # Dispositivos disponibles para el formulario de reglas
    if request.user.is_staff:
        devices = HardwareDevice.objects.filter(is_active=True).select_related("client")
    else:
        portal = request.user.client_portals.first()
        devices = HardwareDevice.objects.filter(
            client=portal, is_active=True) if portal else HardwareDevice.objects.none()

    return render(request, "core/alerts_dashboard.html", {
        "section":          "alerts",
        "events":           events,
        "rules":            rules,
        "all_events":       all_events,
        "clients":          clients,
        "devices":          devices,
        "firing_critical":  firing_critical,
        "firing_warning":   firing_warning,
        "resolved_today":   resolved_today,
        "total_rules":      rules.count(),
        "METRIC_CHOICES":   AlertRule.METRIC_CHOICES,
        "SEVERITY_CHOICES": AlertRule.SEVERITY_CHOICES,
    })


@login_required
@require_POST
def alert_rule_create(request):
    """Crea una nueva regla de alerta vía POST."""
    try:
        client_id  = request.POST.get("client_id")
        device_id  = request.POST.get("device_id") or None
        metric     = request.POST.get("metric")
        threshold  = float(request.POST.get("threshold", 90))
        severity   = request.POST.get("severity", "warning")
        cooldown   = int(request.POST.get("cooldown_minutes", 30))
        notify     = request.POST.get("notify_email") == "on"

        client = get_object_or_404(Client, pk=client_id)
        device = get_object_or_404(HardwareDevice, pk=device_id) if device_id else None

        if metric not in dict(AlertRule.METRIC_CHOICES):
            return JsonResponse({"error": "Métrica inválida"}, status=400)

        AlertRule.objects.create(
            client=client,
            device=device,
            metric=metric,
            threshold=threshold,
            severity=severity,
            cooldown_minutes=cooldown,
            notify_email=notify,
        )
        return JsonResponse({"status": "ok"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


@login_required
@require_POST
def alert_rule_toggle(request, rule_id):
    """Activa/desactiva una regla."""
    rule = get_object_or_404(AlertRule, pk=rule_id)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active"])
    return JsonResponse({"status": "ok", "is_active": rule.is_active})


@login_required
@require_POST
def alert_rule_delete(request, rule_id):
    """Elimina una regla."""
    rule = get_object_or_404(AlertRule, pk=rule_id)
    rule.delete()
    return JsonResponse({"status": "ok"})


@login_required
@require_POST
def alert_event_resolve(request, event_id):
    """Marca un evento de alerta como resuelto."""
    event = get_object_or_404(AlertEvent, pk=event_id)
    event.status      = "resolved"
    event.resolved_at = timezone.now()
    event.save(update_fields=["status", "resolved_at"])
    return JsonResponse({"status": "ok"})


@login_required
@require_POST
def alert_event_silence(request, event_id):
    """Silencia un evento (no crea más alertas para este)."""
    event = get_object_or_404(AlertEvent, pk=event_id)
    event.status = "silenced"
    event.save(update_fields=["status"])
    return JsonResponse({"status": "ok"})
