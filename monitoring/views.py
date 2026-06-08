from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.contrib import messages
from core.models import Client, Domain, M365License, M365Tenant
from .services import refresh_domain, sync_m365_client


@login_required
def domain_list(request):
    clients = Client.objects.filter(is_active=True).prefetch_related("domains")
    return render(request, "monitoring/domain_list.html", {"clients": clients})


@login_required
def domain_refresh_htmx(request, domain_id):
    """HTMX endpoint: refresca un dominio y devuelve el fragmento actualizado."""
    domain = get_object_or_404(Domain, pk=domain_id)
    try:
        refresh_domain(domain)
        messages.success(request, f"{domain.fqdn} actualizado correctamente.")
    except Exception as e:
        messages.error(request, f"Error actualizando {domain.fqdn}: {e}")
    return render(request, "monitoring/partials/domain_row.html", {"domain": domain})


@login_required
def m365_sync_htmx(request, client_id):
    """HTMX endpoint: sincroniza licencias M365 de un cliente."""
    client = get_object_or_404(Client, pk=client_id)
    if sync_m365_client(client):
        messages.success(request, f"Licencias M365 de {client} sincronizadas.")
    else:
        messages.error(request, f"Error sincronizando M365 de {client}.")
    licenses = client.m365_licenses.all()
    return render(request, "monitoring/partials/m365_licenses.html",
                  {"client": client, "licenses": licenses})
