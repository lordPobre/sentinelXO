import logging
from celery import shared_task

logger = logging.getLogger("perseus")


@shared_task(name="emailmon.check_smtp_hourly")
def check_smtp_hourly():
    """Tarea horaria: verifica SMTP y crea incidente si falla."""
    from .services import check_smtp_connectivity
    from core.models import MaintenanceIncident, Client
    from django.conf import settings

    check = check_smtp_connectivity()

    if check.status != "ok":
        # Crear incidente global (sin cliente específico) si SMTP falla
        # Buscar si ya hay un incidente abierto de SMTP para no duplicar
        existing = MaintenanceIncident.objects.filter(
            title__startswith="SMTP",
            is_resolved=False,
        ).first()

        if not existing:
            MaintenanceIncident.objects.create(
                client=Client.objects.filter(is_active=True).first(),
                title=f"SMTP {check.smtp_host}:{check.smtp_port} no responde",
                description=(
                    f"La verificación SMTP falló con estado '{check.status}'.\n"
                    f"Error: {check.error_msg}\n"
                    f"Tiempo: {check.response_ms}ms"
                ),
                severity="high",
            )
            logger.warning(f"Incidente SMTP creado: {check.error_msg}")

    return {"status": check.status, "ms": check.response_ms}


@shared_task(name="emailmon.cleanup_old_logs")
def cleanup_old_logs():
    """Mensual: limpia logs de email de más de 90 días."""
    from django.utils import timezone
    from .models import EmailLog, SmtpCheck

    cutoff = timezone.now() - timezone.timedelta(days=90)
    deleted_logs  = EmailLog.objects.filter(sent_at__lt=cutoff).delete()[0]
    deleted_checks = SmtpCheck.objects.filter(checked_at__lt=cutoff).delete()[0]
    logger.info(f"Limpieza email logs: {deleted_logs} logs, {deleted_checks} checks eliminados")
    return {"logs": deleted_logs, "checks": deleted_checks}


@shared_task(name="emailmon.check_m365_all_clients")
def check_m365_all_clients():
    """
    Cada hora: verifica conectividad SMTP M365 y Graph API
    para todos los clientes con M365 configurado.
    """
    from core.models import Client
    from .services import check_m365_smtp

    # 1. Verificar SMTP global de M365 (una sola vez, no por cliente)
    global_result = check_m365_smtp(client=None)
    logger.info(f"M365 SMTP global: {global_result['overall']} — "
                f"smtp={global_result['smtp'].get('ms','?')}ms")

    # 2. Verificar Graph API por cliente con M365 configurado
    clients = Client.objects.filter(
        is_active=True,
        m365_tenant__is_active=True,
    )
    results = {"ok": 0, "warning": 0, "error": 0}

    for client in clients:
        result = check_m365_smtp(client=client)
        results[result["overall"]] = results.get(result["overall"], 0) + 1

        # Si hay error de Graph API, crear incidente
        if result["graph"] and result["graph"].get("status") == "error":
            from core.models import MaintenanceIncident
            if not MaintenanceIncident.objects.filter(
                client=client,
                title__icontains="Graph API",
                is_resolved=False,
            ).exists():
                MaintenanceIncident.objects.create(
                    client=client,
                    title=f"Error conexión Microsoft 365 — {client.company_name}",
                    description=(
                        f"La verificación de Graph API falló.\n"
                        f"Error: {result['graph'].get('error', '—')}\n"
                        f"Tenant: {client.m365_tenant.tenant_id}"
                    ),
                    category="license",
                    severity="high",
                    notify_email=True,
                )
                logger.warning(f"Incidente M365 creado para {client}")

    logger.info(f"M365 check completo: {results}")
    return results
