import logging
import io
from core.models import Client, MonthlyReport
from .generator import build_report_pdf
from django.core.mail import EmailMessage
from django.conf import settings
from celery import shared_task
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from emailmon.services import send_tracked_email

logger = logging.getLogger("perseus")


@shared_task(name="reports.generate_monthly_reports_all")
def generate_monthly_reports_all():
    now = timezone.now()
    last_month = now - relativedelta(months=1)

    clients = Client.objects.filter(is_active=True)
    for client in clients:
        generate_monthly_report_client.delay(
            str(client.id),
            last_month.year,
            last_month.month,
        )
    logger.info(f"Encolados {clients.count()} reportes para {last_month.year}/{last_month.month:02d}")


@shared_task(name="reports.generate_monthly_report_client")
def generate_monthly_report_client(client_id: str, year: int, month: int):
    try:
        client = Client.objects.get(pk=client_id)
    except Client.DoesNotExist:
        logger.error(f"Cliente no encontrado: {client_id}")
        return

    report, _ = MonthlyReport.objects.get_or_create(
        client=client, period_year=year, period_month=month,
        defaults={"status": "pending"}
    )
    if report.status == "sent":
        logger.info(f"Reporte ya enviado: {client} {year}/{month}")
        return

    report.status = "generating"
    report.save(update_fields=["status"])

    try:
        pdf_bytes, summary = build_report_pdf(client, year, month)
        report.summary_data = summary
        report.status = "ready"
        report.generated_at = timezone.now()
        report.save(update_fields=["status", "generated_at", "summary_data"])

        month_name = timezone.datetime(year, month, 1).strftime("%B %Y")
        filename = f"reporte_mantenimiento_{client.company_name.lower().replace(' ', '_')}_{year}_{month:02d}.pdf"
        send_tracked_email(
            subject=f"[{settings.SENTINEL_COMPANY_NAME}] Reporte de Mantenimiento — {month_name}",
            body=(
                f"Estimado equipo de {client.company_name},\n\n"
                f"Adjunto encontrará el reporte de mantenimiento preventivo correspondiente a {month_name}.\n\n"
                f"Ante cualquier consulta, contáctenos en {settings.SENTINEL_SUPPORT_EMAIL}.\n\n"
                f"Saludos,\n{settings.SENTINEL_COMPANY_NAME}"
            ),
            to=[client.contact_email],
            category="report",
            client=client,
            attachments=[(filename, pdf_bytes, "application/pdf")],
        )

        report.status = "sent"
        report.sent_at = timezone.now()
        report.save(update_fields=["status", "sent_at"])
        logger.info(f"Reporte enviado: {client} {year}/{month}")

    except Exception as e:
        report.status = "error"
        report.error_message = str(e)
        report.save(update_fields=["status", "error_message"])
        logger.error(f"Error generando reporte {client} {year}/{month}: {e}")
        raise
