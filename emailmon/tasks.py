import logging
from celery import shared_task
from core.models import Client
from .services import check_m365_graph_health

logger = logging.getLogger("perseus")


@shared_task(name="emailmon.run_m365_checks")
def run_m365_checks():
    """
    Ejecuta el chequeo de salud M365 (Graph API) para cada cliente con tenant
    activo. Cada ejecución crea una fila SmtpCheck (host 'graph.microsoft.com (M365)')
    que alimenta el gráfico de latencia y el historial del dashboard M365.

    Programar en CELERY_BEAT_SCHEDULE (ver nota). Cadencia sugerida: 15–30 min.
    """
    clients = Client.objects.filter(is_active=True, m365_tenant__is_active=True)
    count = 0
    for client in clients:
        try:
            check_m365_graph_health(client)
            count += 1
        except Exception as e:
            logger.error(f"run_m365_checks: fallo para {client}: {e}")
    logger.info(f"run_m365_checks: {count} cliente(s) verificado(s)")
    return count
