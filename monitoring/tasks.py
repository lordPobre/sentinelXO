import logging
from celery import shared_task
from django.utils import timezone
from core.models import Domain,Client
from .services import refresh_domain,sync_m365_client
from django.core.mail import send_mail
from django.conf import settings

logger = logging.getLogger("perseus")

@shared_task(name="monitoring.refresh_all_domains")
def refresh_all_domains():
    domains = Domain.objects.filter(client__is_active=True)
    ok = 0
    errors = 0
    for domain in domains:
        try:
            refresh_domain(domain)
            ok += 1
        except Exception as e:
            logger.error(f"Error actualizando {domain.fqdn}: {e}")
            errors += 1

    logger.info(f"Dominios actualizados: {ok} OK, {errors} errores")
    return {"ok": ok, "errors": errors}


@shared_task(name="monitoring.refresh_single_domain")
def refresh_single_domain(domain_id: int):
    try:
        domain = Domain.objects.get(pk=domain_id)
        refresh_domain(domain)
        return {"status": "ok", "fqdn": domain.fqdn}
    except Domain.DoesNotExist:
        return {"status": "error", "message": "Dominio no encontrado"}


@shared_task(name="monitoring.sync_m365_all_clients")
def sync_m365_all_clients():
    clients = Client.objects.filter(is_active=True, m365_tenant__is_active=True)
    results = {"ok": 0, "errors": 0}
    for client in clients:
        if sync_m365_client(client):
            results["ok"] += 1
        else:
            results["errors"] += 1

    logger.info(f"M365 sync: {results['ok']} OK, {results['errors']} errores")
    return results


@shared_task(name="monitoring.check_expiry_alerts")
def check_expiry_alerts():
    alert_thresholds = [90, 30, 7]
    today = timezone.now().date()

    for domain in Domain.objects.filter(client__is_active=True, expiry_date__isnull=False):
        days = domain.days_until_expiry
        if days in alert_thresholds:
            subject = f"⚠️ Dominio próximo a vencer: {domain.fqdn} ({days} días)"
            message = (
                f"Estimado equipo de {domain.client.company_name},\n\n"
                f"El dominio {domain.fqdn} vence el {domain.expiry_date.strftime('%d/%m/%Y')} "
                f"({days} días).\n\n"
                f"Por favor coordine la renovación a tiempo.\n\n"
                f"— {settings.SENTINEL_COMPANY_NAME}"
            )
            try:
                from emailmon.services import send_tracked_email
                send_tracked_email(
                    subject=subject,
                    body=message,
                    to=[domain.client.contact_email],
                    category="alert",
                    client=domain.client,
                )
                logger.info(f"Alerta enviada: {domain.fqdn} ({days}d) → {domain.client.contact_email}")
            except Exception as e:
                logger.error(f"Error enviando alerta {domain.fqdn}: {e}")
