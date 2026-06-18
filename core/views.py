import logging
from core.models import AuditLog
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.db.models import Count, Q
from django.utils import timezone
from core.models import (Client, HardwareDevice, TelemetrySnapshot,
                          Domain, M365License, MaintenanceIncident)
from django.db.models import F
from core.notifications import notify_incident_resolved
from django.http import HttpResponseForbidden

logger = logging.getLogger("perseus")


def _is_admin(user):
    return user.is_staff or user.is_superuser


@login_required
def home(request):
    """Redirige al dashboard correcto según el rol del usuario."""
    if _is_admin(request.user):
        return redirect("dashboard:admin-overview")
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

    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
    total_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__gte=month_start
    ).count()
    online_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__gte=month_start, uptime_seconds__gt=0
    ).count()
    uptime_percent = round((online_snaps / total_snaps * 100), 1) if total_snaps > 0 else None

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
    
    return F("total_licenses")


# ─── HTMX fragments ──────────────────────────────────────────────────────────

@login_required
def htmx_device_detail(request, device_id):
    """Fragmento HTMX: detalle de un dispositivo con sus últimos snapshots."""
    device = get_object_or_404(HardwareDevice, pk=device_id)
    snapshots = device.snapshots.all()[:24]  
    return render(request, "dashboard/partials/device_detail.html",
                  {"device": device, "snapshots": snapshots})


@login_required
def htmx_incident_resolve(request, incident_id):
    """Fragmento HTMX: marca incidente como resuelto, notifica y devuelve la fila."""
    if request.method == "POST":
        incident = get_object_or_404(MaintenanceIncident, pk=incident_id)
        incident.resolve()

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

    if not _is_admin(request.user):
        if not request.user.client_portals.filter(pk=device.client_id).exists():
            
            return HttpResponseForbidden()

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
        return HttpResponseForbidden()
    
    logs = AuditLog.objects.select_related("user").order_by("-timestamp")[:200]
    return render(request, "dashboard/audit_log.html", {
        "section": "audit",
        "logs":    logs,
    })
