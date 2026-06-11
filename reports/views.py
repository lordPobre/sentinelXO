from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.contrib import messages
from django.utils import timezone
from core.models import Client, MonthlyReport,HardwareDevice
from .device_report import build_device_report_pdf
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


@login_required
def device_report_download(request, device_id):
    device = get_object_or_404(HardwareDevice, pk=device_id, is_active=True)

    if not request.user.is_staff:
        if not request.user.client_portals.filter(pk=device.client_id).exists():
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Sin acceso")

    now = timezone.now()
    try:
        year        = int(request.GET.get("year",        now.year))
        month       = int(request.GET.get("month",       now.month))
        granularity = request.GET.get("granularity", "daily")
        if granularity not in ("daily", "weekly"):
            granularity = "daily"
    except (ValueError, TypeError):
        year, month, granularity = now.year, now.month, "daily"

    try:
        pdf_bytes, _ = build_device_report_pdf(device, year, month, granularity)
    except Exception as e:
        return HttpResponse(f"Error generando reporte: {e}", status=500)

    gran_str = "diario" if granularity == "daily" else "semanal"
    filename = (
        f"reporte_{device.display_name.replace(' ', '_')}_"
        f"{year}_{month:02d}_{gran_str}.pdf"
    )
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"' 
    return response
