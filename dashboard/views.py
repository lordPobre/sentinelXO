import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.db.models import Count, Q
from django.utils import timezone
from core.models import (Client, HardwareDevice, TelemetrySnapshot,
                          Domain, M365License, MaintenanceIncident)

logger = logging.getLogger("perseus")


def _is_admin(user):
    return user.is_staff or user.is_superuser


@login_required
def home(request):
    """Redirige al dashboard correcto según el rol del usuario."""
    if _is_admin(request.user):
        return redirect("dashboard:admin-overview")
    # Usuario de cliente
    clients = request.user.client_portals.filter(is_active=True)
    if clients.count() == 1:
        return redirect("dashboard:client-portal", client_id=clients.first().id)
    return redirect("dashboard:client-select")


# ─── PANEL ADMINISTRADOR (Sentinel XO) ───────────────────────────────────────────

@login_required
def admin_overview(request):
    if not _is_admin(request.user):
        return redirect("dashboard:home")

    clients = Client.objects.filter(is_active=True).prefetch_related("devices", "domains")
    devices_total = HardwareDevice.objects.filter(is_active=True).count()
    devices_offline = sum(1 for d in HardwareDevice.objects.filter(is_active=True) if not d.is_online)
    domains_critical = Domain.objects.filter(status__in=["critical", "expired"]).count()
    incidents_open = MaintenanceIncident.objects.filter(is_resolved=False).count()

    context = {
        "clients": clients,
        "devices_total": devices_total,
        "devices_offline": devices_offline,
        "domains_critical": domains_critical,
        "incidents_open": incidents_open,
        "section": "overview",
    }
    return render(request, "dashboard/admin_overview.html", context)


@login_required
def admin_clients(request):
    if not _is_admin(request.user):
        return redirect("dashboard:home")
    clients = Client.objects.all().prefetch_related("devices", "domains", "m365_licenses")
    return render(request, "dashboard/admin_clients.html", {"clients": clients, "section": "clients"})


@login_required
def admin_client_detail(request, client_id):
    if not _is_admin(request.user):
        return redirect("dashboard:home")
    client = get_object_or_404(Client, pk=client_id)
    devices = client.devices.filter(is_active=True).prefetch_related("snapshots")
    domains = client.domains.all()
    licenses = client.m365_licenses.filter(capability_status="Enabled", total_licenses__lt=10000, total_licenses__gt=0)
    incidents = client.incidents.order_by("-created_at")[:20]
    context = {
        "client": client,
        "devices": devices,
        "domains": domains,
        "licenses": licenses,
        "incidents": incidents,
        "section": "clients",
    }
    return render(request, "dashboard/admin_client_detail.html", context)


# ─── PORTAL DEL CLIENTE ───────────────────────────────────────────────────────

@login_required
def client_select(request):
    """Para usuarios con acceso a múltiples clientes."""
    clients = request.user.client_portals.filter(is_active=True)
    if clients.count() == 1:
        return redirect("dashboard:client-portal", client_id=clients.first().id)
    return render(request, "dashboard/client_select.html", {"clients": clients})


@login_required
def client_portal(request, client_id):
    """Dashboard principal del cliente final."""
    if _is_admin(request.user):
        client = get_object_or_404(Client, pk=client_id)
    else:
        client = get_object_or_404(request.user.client_portals, pk=client_id, is_active=True)

    devices = client.devices.filter(is_active=True)
    domains = client.domains.all()
    licenses = client.m365_licenses.filter(capability_status="Enabled", total_licenses__lt=10000, total_licenses__gt=0)
    incidents_recent = client.incidents.filter(
        created_at__gte=timezone.now() - timezone.timedelta(days=30)
    ).order_by("-created_at")[:10]
    incidents_resolved_count = client.incidents.filter(
        resolved_at__gte=timezone.now() - timezone.timedelta(days=30),
        is_resolved=True
    ).count()

    # Uptime del mes actual
    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
    total_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__gte=month_start
    ).count()
    online_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__gte=month_start, uptime_seconds__gt=0
    ).count()
    uptime_percent = round((online_snaps / total_snaps * 100), 1) if total_snaps > 0 else None

    # Estado de alertas
    domains_critical = domains.filter(status__in=["critical", "expired"]).count()
    domains_warning = domains.filter(status="warning").count()
    licenses_full = licenses.filter(consumed_licenses__gte=models_gte_total()).count() if licenses.exists() else 0

    context = {
        "client": client,
        "devices": devices,
        "domains": domains,
        "licenses": licenses,
        "incidents_recent": incidents_recent,
        "incidents_resolved_count": incidents_resolved_count,
        "uptime_percent": uptime_percent,
        "domains_critical": domains_critical,
        "domains_warning": domains_warning,
        "section": "portal",
    }
    return render(request, "dashboard/client_portal.html", context)


def models_gte_total():
    from django.db.models import F
    return F("total_licenses")


# ─── HTMX fragments ──────────────────────────────────────────────────────────

@login_required
def htmx_device_detail(request, device_id):
    """Fragmento HTMX: detalle de un dispositivo con sus últimos snapshots."""
    device = get_object_or_404(HardwareDevice, pk=device_id)
    snapshots = device.snapshots.all()[:24]  # últimas 24 capturas (~6h a 15 min)
    return render(request, "dashboard/partials/device_detail.html",
                  {"device": device, "snapshots": snapshots})


@login_required
def htmx_incident_create(request, client_id):
    """Fragmento HTMX: crea un incidente, envía notificación y devuelve la fila."""
    if request.method == "POST":
        from core.notifications import notify_incident_created
        client   = get_object_or_404(Client, pk=client_id)
        title    = request.POST.get("title", "Sin título").strip()
        severity = request.POST.get("severity", "medium")
        category = request.POST.get("category", "other")
        description = request.POST.get("description", "")
        notify   = request.POST.get("notify", "true") != "false"

        # Detectar categoría automáticamente si no se especificó
        if category == "other" and title:
            t = title.lower()
            if any(w in t for w in ["dominio", "domain", "dns", "vence", "renovar"]):
                category = "domain"
            elif any(w in t for w in ["email", "correo", "smtp", "brevo", "mail"]):
                category = "email"
            elif any(w in t for w in ["licencia", "m365", "microsoft", "office"]):
                category = "license"
            elif any(w in t for w in ["red", "network", "wifi", "internet", "conexión"]):
                category = "network"
            elif any(w in t for w in ["cpu", "ram", "disco", "equipo", "pc", "laptop",
                                       "servidor", "hardware", "memoria"]):
                category = "hardware"

        incident = MaintenanceIncident.objects.create(
            client=client,
            title=title or "Sin título",
            description=description,
            severity=severity,
            category=category,
            notify_email=notify,
        )

        # Enviar notificación en background (no bloquea la respuesta HTMX)
        if notify:
            try:
                notify_incident_created(incident)
            except Exception as e:
                logger.warning(f"Error enviando notificación de incidente: {e}")

        # Generar diagnóstico IA en background (no bloquea la respuesta HTMX)
        try:
            import threading
            from core.views_ai import diagnose_incident
            def run_diagnosis():
                diag = diagnose_incident(incident)
                if diag:
                    incident.ai_diagnosis = diag
                    incident.save(update_fields=["ai_diagnosis"])
            threading.Thread(target=run_diagnosis, daemon=True).start()
        except Exception as e:
            logger.warning(f"Error iniciando diagnóstico IA: {e}")

        return render(request, "dashboard/partials/incident_row.html",
                      {"incident": incident})
    return HttpResponse(status=405)


@login_required
def htmx_incident_resolve(request, incident_id):
    """Fragmento HTMX: marca incidente como resuelto, notifica y devuelve la fila."""
    if request.method == "POST":
        from core.notifications import notify_incident_resolved
        incident = get_object_or_404(MaintenanceIncident, pk=incident_id)
        incident.resolve()

        # Notificar resolución
        try:
            notify_incident_resolved(incident)
        except Exception as e:
            logger.warning(f"Error enviando notificación de resolución: {e}")

        return render(request, "dashboard/partials/incident_row.html",
                      {"incident": incident})
    return HttpResponse(status=405)


@login_required
def realtime_dashboard(request, client_id):
    """Dashboard de monitoreo en tiempo real con polling cada 5 segundos."""
    if _is_admin(request.user):
        client = get_object_or_404(Client, pk=client_id)
    else:
        client = get_object_or_404(request.user.client_portals, pk=client_id, is_active=True)

    devices = client.devices.filter(is_active=True)
    return render(request, "dashboard/realtime.html", {
        "client": client,
        "devices": devices,
        "section": "realtime",
    })


@login_required
def device_detail_live(request, device_id):
    """Vista de detalle en tiempo real de un dispositivo específico."""
    device = get_object_or_404(HardwareDevice, pk=device_id, is_active=True)

    # Verificar acceso
    if not _is_admin(request.user):
        if not request.user.client_portals.filter(pk=device.client_id).exists():
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden()

    # Últimos 60 snapshots para el historial (~5 minutos a 5s de intervalo)
    snapshots = list(device.snapshots.order_by("captured_at")[::-1][:60][::-1])

    return render(request, "dashboard/device_live.html", {
        "device": device,
        "client": device.client,
        "snapshots": snapshots,
        "section": "realtime",
    })



@login_required
def audit_log_view(request):
    """Vista del log de auditoría — solo staff."""
    if not request.user.is_staff:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    from core.models import AuditLog
    logs = AuditLog.objects.select_related("user").order_by("-timestamp")[:200]
    return render(request, "dashboard/audit_log.html", {
        "section": "audit",
        "logs":    logs,
    })
