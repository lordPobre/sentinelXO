"""
Vistas de tiempo real para el dashboard de Perseus.
Cada endpoint devuelve HTML puro (fragmento HTMX).
El frontend hace polling cada 5 segundos con hx-trigger="every 5s".
"""
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from core.models import HardwareDevice, TelemetrySnapshot, Client
import json


@login_required
def rt_device_card(request, device_id):
    """
    Fragmento HTMX: estado en tiempo real de UN dispositivo.
    Polleado cada 5s desde el dashboard del cliente.
    """
    device = get_object_or_404(HardwareDevice, pk=device_id, is_active=True)
    snap   = device.snapshots.first()   # el más reciente (orden: -captured_at)

    # Calcular historial de CPU para la mini-sparkline (últimas 20 capturas)
    history = list(
        device.snapshots
        .values_list("cpu_percent", "ram_used_percent", "captured_at")
        .order_by("-captured_at")[:20]
    )
    history.reverse()   # cronológico para el gráfico

    cpu_history = [h[0] for h in history]
    ram_history = [h[1] for h in history]

    # Calcular uptime del día
    today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total_today = device.snapshots.filter(captured_at__gte=today_start).count()
    online_today = device.snapshots.filter(
        captured_at__gte=today_start, uptime_seconds__gt=0
    ).count()
    uptime_today = round((online_today / total_today * 100), 1) if total_today else None

    context = {
        "device":      device,
        "snap":        snap,
        "cpu_history": json.dumps(cpu_history),
        "ram_history": json.dumps(ram_history),
        "uptime_today": uptime_today,
        "now":         timezone.now(),
    }
    html = render_to_string("dashboard/partials/rt_device_card.html", context, request)
    return HttpResponse(html)


@login_required
def rt_fleet_overview(request, client_id):
    """
    Fragmento HTMX: tarjetas de TODOS los dispositivos de un cliente.
    Polleado cada 5s desde el portal del cliente.
    """
    client  = get_object_or_404(Client, pk=client_id)
    devices = client.devices.filter(is_active=True).prefetch_related("snapshots")

    # Métricas globales para los KPIs
    total    = devices.count()
    online   = sum(1 for d in devices if d.is_online)
    warning  = sum(1 for d in devices if d.status == "warning")
    offline  = total - online

    context = {
        "client":  client,
        "devices": devices,
        "total":   total,
        "online":  online,
        "warning": warning,
        "offline": offline,
        "now":     timezone.now(),
    }
    html = render_to_string("dashboard/partials/rt_fleet_overview.html", context, request)
    return HttpResponse(html)


@login_required
def rt_kpi_bar(request, client_id):
    """
    Fragmento HTMX: barra de KPIs superior del portal cliente.
    Polleado cada 10s.
    """
    client  = get_object_or_404(Client, pk=client_id)
    devices = client.devices.filter(is_active=True)

    month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total_snaps  = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__gte=month_start
    ).count()
    online_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__gte=month_start, uptime_seconds__gt=0
    ).count()
    uptime = round(online_snaps / total_snaps * 100, 1) if total_snaps else None

    incidents_resolved = client.incidents.filter(
        resolved_at__gte=timezone.now() - timezone.timedelta(days=30),
        is_resolved=True
    ).count()

    context = {
        "uptime_percent":        uptime,
        "incidents_resolved":    incidents_resolved,
        "devices_total":         devices.count(),
        "devices_online":        sum(1 for d in devices if d.is_online),
    }
    html = render_to_string("dashboard/partials/rt_kpi_bar.html", context, request)
    return HttpResponse(html)
