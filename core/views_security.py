"""
Sentinel XO — Panel de Postura de Seguridad M365
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.db import connection
from django.http import HttpResponseForbidden
from core.models import Client, SecurityCheck, SecurityAnomalyEvent, SignInAnomalyEvent, HardwareDevice, SoftwareSnapshot
from core.security import check_m365_security_posture
from core.views_ai import generate_security_analysis, generate_software_cve_analysis
from core.notifications_telegram import send_telegram_test

@login_required
def security_dashboard(request):
    """Vista principal del panel de seguridad — lista todos los clientes."""
    try:
        tables = connection.introspection.table_names()
        if "core_securitycheck" not in tables:
            return render(request, "core/security_dashboard.html", {
                "section": "security",
                "migration_pending": True,
                "clients_security": [],
            })
    except Exception:
        pass

    if request.user.is_staff:
        clients = Client.objects.filter(is_active=True)
    else:
        portal = request.user.client_portals.first()
        if not portal:
            return HttpResponseForbidden()
        clients = Client.objects.filter(pk=portal.pk)

    clients_security = []
    for client in clients:
        latest = SecurityCheck.objects.filter(client=client).order_by("-checked_at").first()
        anomalies_open = SecurityAnomalyEvent.objects.filter(
            device__client=client, status="open"
        ).count()
        
        signin_anomalies_open = SignInAnomalyEvent.objects.filter(
            client=client, status="open"
        ).count()
        m365_configured = bool(getattr(client, "m365_tenant", None) and client.m365_tenant.is_active)
        ai = latest.ai_summary if (latest and latest.ai_summary) else None

        clients_security.append({
            "client":           client,
            "latest":           latest,
            "anomalies_open":   anomalies_open + signin_anomalies_open,
            "m365_configured":  m365_configured,
            "ai_risk":          ai.get("nivel_riesgo") if ai else None,
        })

    return render(request, "core/security_dashboard.html", {
        "section":          "security",
        "clients_security": clients_security,
    })


@login_required
def security_client_detail(request, client_id):
    """Vista de detalle de seguridad para un cliente específico."""
    
    client = get_object_or_404(Client, pk=client_id)

    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=client_id).first()
        if not portal:
            return HttpResponseForbidden()

    latest = SecurityCheck.objects.filter(client=client).order_by("-checked_at").first()

    open_anomalies = list(SecurityAnomalyEvent.objects.filter(
        device__client=client, status="open"
    ).select_related("device").order_by("-detected_at"))
    reviewed_anomalies = list(SecurityAnomalyEvent.objects.filter(
        device__client=client
    ).exclude(status="open").select_related("device").order_by("-detected_at")[:20])
    anomalies = open_anomalies + reviewed_anomalies

    
    open_signin = list(SignInAnomalyEvent.objects.filter(
        client=client, status="open"
    ).order_by("-detected_at"))
    reviewed_signin = list(SignInAnomalyEvent.objects.filter(
        client=client
    ).exclude(status="open").order_by("-detected_at")[:20])
    signin_anomalies = open_signin + reviewed_signin

    return render(request, "core/security_client_detail.html", {
        "section":        "security",
        "client":         client,
        "latest":         latest,
        "anomalies":      anomalies,
        "anomalies_open": len(open_anomalies),
        "signin_anomalies":      signin_anomalies,
        "signin_anomalies_open": len(open_signin),
        "m365_configured": bool(getattr(client, "m365_tenant", None) and client.m365_tenant.is_active),
    })


@login_required
def security_check_now(request, client_id):
    """POST — ejecuta el chequeo de seguridad M365 para un cliente."""
    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=client_id).first()
        if not portal:
            return HttpResponseForbidden()

    client = get_object_or_404(Client, pk=client_id)

    if request.method == "POST":
        check_m365_security_posture(client)

    latest = client.security_checks.order_by("-checked_at").first()

    return render(request, "core/partials/security_status.html", {
        "client": client,
        "latest": latest,
    })


@login_required
def security_anomaly_acknowledge(request, anomaly_id):
    """POST — marca una anomalía de seguridad (agente) como revisada."""
    anomaly = get_object_or_404(SecurityAnomalyEvent, pk=anomaly_id)

    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=anomaly.device.client_id).first()
        if not portal:
            return HttpResponseForbidden()

    if request.method == "POST":
        anomaly.status = "acknowledged"
        anomaly.save(update_fields=["status"])

    return render(request, "core/partials/security_anomaly_row.html", {"anomaly": anomaly})


@login_required
def signin_anomaly_acknowledge(request, anomaly_id):
    """POST — marca una anomalía de inicio de sesión (M365) como revisada."""
    anomaly = get_object_or_404(SignInAnomalyEvent, pk=anomaly_id)

    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=anomaly.client_id).first()
        if not portal:
            return HttpResponseForbidden()

    if request.method == "POST":
        anomaly.status = "acknowledged"
        anomaly.save(update_fields=["status"])

    return render(request, "core/partials/signin_anomaly_row.html", {"anomaly": anomaly})


@login_required
def security_ai_analysis(request, client_id):
    """POST — genera o regenera el análisis de seguridad con IA para un cliente."""
    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=client_id).first()
        if not portal:
            return HttpResponseForbidden()

    client = get_object_or_404(Client, pk=client_id)
    latest = client.security_checks.order_by("-checked_at").first()

    if not latest:
        return render(request, "core/partials/security_ai_panel.html", {
            "client": client, "latest": None, "error": "Ejecuta primero una verificación.",
        })

    force = request.GET.get("force", "false") == "true" or request.method == "POST"
    if latest.ai_summary and not force:
        return render(request, "core/partials/security_ai_panel.html", {
            "client": client, "latest": latest,
        })

    analysis = generate_security_analysis(client, latest)
    if analysis:
        latest.ai_summary = analysis
        latest.save(update_fields=["ai_summary"])
        return render(request, "core/partials/security_ai_panel.html", {
            "client": client, "latest": latest,
        })

    return render(request, "core/partials/security_ai_panel.html", {
        "client": client, "latest": latest,
        "error": "No se pudo generar el análisis. Intenta de nuevo.",
    })


@login_required
def software_inventory_view(request, device_id):
    """Vista de inventario de software de un dispositivo."""
    device = get_object_or_404(HardwareDevice, pk=device_id)

    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=device.client_id).first()
        if not portal:
            return HttpResponseForbidden()

    snapshot = SoftwareSnapshot.objects.filter(device=device).first()

    return render(request, "core/software_inventory.html", {
        "section":  "security",
        "device":   device,
        "client":   device.client,
        "snapshot": snapshot,
    })


@login_required
def software_cve_analysis(request, device_id):
    """POST — genera o regenera el análisis CVE del inventario de software."""
    device = get_object_or_404(HardwareDevice, pk=device_id)

    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=device.client_id).first()
        if not portal:
            return HttpResponseForbidden()

    snapshot = SoftwareSnapshot.objects.filter(device=device).first()
    if not snapshot or not snapshot.software_list:
        return render(request, "core/partials/software_cve_panel.html", {
            "device": device, "snapshot": None,
            "error": "Aún no se ha recibido el inventario de software de este equipo.",
        })

    force = request.GET.get("force", "false") == "true" or request.method == "POST"
    if snapshot.cve_analysis and not force:
        return render(request, "core/partials/software_cve_panel.html", {
            "device": device, "snapshot": snapshot,
        })

    analysis = generate_software_cve_analysis(device, snapshot.software_list)
    if analysis:
        snapshot.cve_analysis = analysis
        snapshot.cve_checked_at = timezone.now()
        snapshot.save(update_fields=["cve_analysis", "cve_checked_at"])
        return render(request, "core/partials/software_cve_panel.html", {
            "device": device, "snapshot": snapshot,
        })

    return render(request, "core/partials/software_cve_panel.html", {
        "device": device, "snapshot": snapshot,
        "error": "No se pudo generar el análisis. Intenta de nuevo.",
    })


@login_required
def telegram_test(request, client_id):
    """POST — envía un mensaje de prueba por Telegram al cliente."""
    if not request.user.is_staff:
        portal = request.user.client_portals.filter(pk=client_id).first()
        if not portal:
            return HttpResponseForbidden()

    client = get_object_or_404(Client, pk=client_id)

    success, error = send_telegram_test(client)

    return render(request, "core/partials/telegram_status.html", {
        "client": client, "success": success, "error": error,
    })
