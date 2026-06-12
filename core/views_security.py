"""
Sentinel XO — Panel de Postura de Seguridad M365
"""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.http import HttpResponseForbidden


@login_required
def security_dashboard(request):
    """Vista principal del panel de seguridad."""
    from core.models import Client, SecurityCheck

    # Verificar que la tabla existe (puede no existir si la migración no se aplicó)
    try:
        from django.db import connection
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
        clients = Client.objects.filter(is_active=True, m365_tenant__is_active=True)
    else:
        portal = request.user.client_portals.first()
        if not portal:
            return HttpResponseForbidden()
        clients = Client.objects.filter(pk=portal.pk, m365_tenant__is_active=True)

    clients_security = []
    for client in clients:
        latest = SecurityCheck.objects.filter(client=client).order_by("-checked_at").first()
        clients_security.append({
            "client": client,
            "latest": latest,
        })

    return render(request, "core/security_dashboard.html", {
        "section":          "security",
        "clients_security": clients_security,
    })


@login_required
def security_check_now(request, client_id):
    """POST — ejecuta el chequeo de seguridad M365 para un cliente."""
    from core.models import Client
    from core.security import check_m365_security_posture

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
