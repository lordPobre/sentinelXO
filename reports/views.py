from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.contrib import messages
from core.models import Client, MonthlyReport
from .generator import build_report_pdf


@login_required
def report_list(request):
    reports = MonthlyReport.objects.select_related("client").order_by("-period_year", "-period_month")
    return render(request, "reports/report_list.html", {"reports": reports})


@login_required
def report_download(request, report_id):
    report = get_object_or_404(MonthlyReport, pk=report_id)
    if not report.summary_data:
        return HttpResponse("Reporte no disponible aún.", status=404)
    pdf_bytes, _ = build_report_pdf(report.client, report.period_year, report.period_month)
    filename = f"reporte_{report.client.company_name}_{report.period_year}_{report.period_month:02d}.pdf"
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
def report_generate_now(request, client_id):
    """Genera un reporte manualmente (GET o POST). Genera sincrónicamente y redirige al detalle."""
    from django.utils import timezone
    client = get_object_or_404(Client, pk=client_id)
    now = timezone.now()
    try:
        pdf_bytes, summary = build_report_pdf(client, now.year, now.month)
        MonthlyReport.objects.update_or_create(
            client=client,
            period_year=now.year,
            period_month=now.month,
            defaults={
                "status": "ready",
                "summary_data": summary,
                "generated_at": now,
            }
        )
        messages.success(request, f"Reporte de {client} generado correctamente.")
    except Exception as e:
        messages.error(request, f"Error generando reporte de {client}: {e}")
    return redirect("dashboard:admin-client-detail", client_id=client_id)
