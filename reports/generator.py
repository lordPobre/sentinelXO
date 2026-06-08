"""
Sentinel XO — Generador de Reportes PDF (WeasyPrint)
Diseño moderno, limpio y profesional adaptado desde ReportLab.
"""
import io
from datetime import datetime
from django.utils import timezone
from django.template import Template, Context
from weasyprint import HTML

MESES = {1:"enero", 2:"febrero", 3:"marzo", 4:"abril", 5:"mayo", 6:"junio",
         7:"julio", 8:"agosto", 9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre"}

REPORT_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Reporte de Mantenimiento</title>
    <style>
        @page {
            size: A4;
            margin: 15mm 15mm 20mm 15mm;
            background-color: #ffffff;
            @bottom-right {
                content: "Página " counter(page);
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                font-size: 8pt;
                color: #64748b;
            }
            @bottom-left {
                content: "{{ company }} · {{ support }} · Confidencial";
                font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
                font-size: 8pt;
                color: #64748b;
            }
        }
        
        *, *::before, *::after { box-sizing: border-box; }
        body { font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #334155; margin: 0; padding: 0; line-height: 1.4; }
        .text-right { text-align: right; }
        .text-center { text-align: center; }
        .text-blue { color: #2563eb; }
        .text-green { color: #10b981; }
        .text-red { color: #ef4444; }
        .text-amber { color: #f59e0b; }
        .text-slate-500 { color: #64748b; }
        .text-slate-800 { color: #1e293b; }
        .font-bold { font-weight: bold; }
        .text-xs { font-size: 8pt; }
        
        /* Portada y Header */
        .cover-header {
            width: 100%; background-color: #0f172a; color: #ffffff;
            display: table; padding: 25px 20px;
            margin: -15mm -15mm 20px -15mm; width: calc(100% + 30mm);
        }
        .cover-header-cell { display: table-cell; vertical-align: middle; }
        .header-title { color: #93c5fd; font-size: 10pt; margin-bottom: 4px; }
        .accent-line { height: 4px; background-color: #2563eb; margin-top: -20px; margin-bottom: 25px; margin-left: -15mm; margin-right: -15mm; }

        /* Info del Cliente */
        .client-info-table { width: 100%; background-color: #f8fafc; border-bottom: 3px solid #2563eb; display: table; margin-bottom: 30px; }
        .client-info-cell { display: table-cell; padding: 15px; border-right: 1px solid #e2e8f0; vertical-align: top; }
        .client-info-cell:last-child { border-right: none; }
        .client-label { font-size: 7pt; font-weight: bold; color: #64748b; letter-spacing: 0.5px; margin-bottom: 4px; text-transform: uppercase; }
        .client-value { font-size: 11pt; font-weight: bold; color: #1e293b; }

        /* Cabeceras de Sección */
        .section-header { margin-top: 25px; margin-bottom: 15px; padding-left: 10px; border-left: 4px solid #2563eb; page-break-after: avoid; }
        .section-title { font-size: 12pt; font-weight: bold; color: #1e293b; text-transform: uppercase; letter-spacing: 0.5px; margin: 0; }
        .section-subtitle { font-size: 9pt; color: #64748b; margin-top: 2px; }

        /* KPIs */
        .kpi-container { width: 100%; display: table; background-color: #f8fafc; border-bottom: 3px solid #2563eb; margin-bottom: 30px; page-break-inside: avoid; }
        .kpi-card { display: table-cell; padding: 15px 10px; text-align: center; border-right: 1px solid #e2e8f0; width: 20%; }
        .kpi-card:last-child { border-right: none; }
        .kpi-label { font-size: 7pt; font-weight: bold; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
        .kpi-value { font-size: 22pt; font-weight: bold; margin: 8px 0; }
        .kpi-sub { font-size: 8pt; color: #64748b; }

        /* Tablas */
        .data-table { width: 100%; border-collapse: collapse; margin-bottom: 25px; font-size: 9pt; }
        .data-table th, .data-table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        .data-table th { background-color: #1e293b; color: #ffffff; font-weight: bold; text-transform: uppercase; font-size: 8pt; letter-spacing: 0.5px; }
        .data-table tr:nth-child(even) td { background-color: #f8fafc; }
        
        /* Barras de progreso */
        .progress-wrapper { width: 100%; max-width: 80px; display: inline-block; vertical-align: middle; margin-right: 8px; }
        .progress-track { background-color: #e2e8f0; height: 6px; border-radius: 3px; width: 100%; overflow: hidden; }
        .progress-fill { height: 100%; border-radius: 3px; }
        
        /* Pills */
        .pill { display: inline-block; padding: 3px 8px; border-radius: 12px; font-size: 7.5pt; font-weight: bold; text-align: center; }
        .pill-green { background-color: #d1fae5; color: #065f46; }
        .pill-amber { background-color: #fef3c7; color: #92400e; }
        .pill-red { background-color: #fee2e2; color: #991b1b; }
        .pill-blue { background-color: #dbeafe; color: #1e40af; }
        .pill-slate { background-color: #f1f5f9; color: #475569; }

        .avoid-break { page-break-inside: avoid; }
    </style>
</head>
<body>

    <!-- Header Full Bleed -->
    <div class="cover-header">
        <div class="cover-header-cell">
            <div style="font-size: 18pt; font-weight: bold;">{{ company }}</div>
            <div style="font-size: 9pt; color: #cbd5e1; margin-top: 4px;">Plataforma de Monitoreo Avanzado</div>
        </div>
        <div class="cover-header-cell text-right">
            <div class="header-title">Reporte de Mantenimiento Preventivo</div>
            <div style="font-size: 18pt; font-weight: bold;">{{ month_name|title }} {{ year }}</div>
        </div>
    </div>
    <div class="accent-line"></div>

    <!-- Client Info -->
    <div class="client-info-table">
        <div class="client-info-cell" style="width: 35%;">
            <div class="client-label">Cliente</div>
            <div class="client-value" style="font-size: 14pt;">{{ client.company_name }}</div>
        </div>
        <div class="client-info-cell" style="width: 25%;">
            <div class="client-label">Contacto</div>
            <div class="client-value" style="font-size: 10pt; font-weight: normal;">{{ client.contact_email }}</div>
        </div>
        <div class="client-info-cell" style="width: 20%;">
            <div class="client-label">Plan Activo</div>
            <div class="client-value" style="font-size: 10pt;">{{ client.get_plan_display }}</div>
        </div>
        <div class="client-info-cell text-right" style="width: 20%;">
            <div class="client-label">Generado</div>
            <div class="client-value" style="font-size: 10pt; font-weight: normal;">{{ now_str }}</div>
        </div>
    </div>

    <!-- Resumen Ejecutivo -->
    <div class="section-header">
        <h2 class="section-title">Resumen Ejecutivo</h2>
        <div class="section-subtitle">Métricas clave del período de facturación</div>
    </div>

    <div class="kpi-container">
        <div class="kpi-card">
            <div class="kpi-label">Disponibilidad</div>
            <div class="kpi-value {% if uptime >= 99 %}text-green{% elif uptime >= 95 %}text-amber{% else %}text-red{% endif %}">{{ uptime }}%</div>
            <div class="kpi-sub">promedio del período</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Equipos</div>
            <div class="kpi-value text-blue">{{ devices_count }}</div>
            <div class="kpi-sub">monitorizados activos</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Incidentes Res.</div>
            <div class="kpi-value text-green">{{ inc_ok }}</div>
            <div class="kpi-sub">solucionados este mes</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Pendientes</div>
            <div class="kpi-value {% if inc_open > 0 %}text-red{% else %}text-slate-800{% endif %}">{{ inc_open }}</div>
            <div class="kpi-sub">requieren atención</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-label">Dom. Críticos</div>
            <div class="kpi-value {% if dom_crit > 0 %}text-red{% else %}text-green{% endif %}">{{ dom_crit }}</div>
            <div class="kpi-sub">sin alertas de expiración</div>
        </div>
    </div>

    {% if devices %}
    <div class="section-header">
        <h2 class="section-title">Estado de Dispositivos</h2>
        <div class="section-subtitle">{{ devices|length }} equipos registrados y monitorizados</div>
    </div>

    <table class="data-table">
        <thead>
            <tr>
                <th style="width: 22%">Equipo</th>
                <th style="width: 15%">Tipo</th>
                <th style="width: 18%">Sistema</th>
                <th style="width: 17%">CPU (Promedio)</th>
                <th style="width: 17%">RAM (Promedio)</th>
                <th style="width: 11%">Estado</th>
            </tr>
        </thead>
        <tbody>
            {% for dev in devices %}
            <tr>
                <td class="font-bold">{{ dev.name }}</td>
                <td class="text-slate-500">{{ dev.type }}</td>
                <td class="text-slate-500">{{ dev.os }}</td>
                <td>
                    {% if dev.cpu is not None %}
                    <div class="progress-wrapper">
                        <div class="progress-track"><div class="progress-fill" style="width: {{ dev.cpu }}%; background-color: {{ dev.cpu_color }};"></div></div>
                    </div>
                    <span class="text-xs">{{ dev.cpu }}%</span>
                    {% else %}—{% endif %}
                </td>
                <td>
                    {% if dev.ram is not None %}
                    <div class="progress-wrapper">
                        <div class="progress-track"><div class="progress-fill" style="width: {{ dev.ram }}%; background-color: {{ dev.ram_color }};"></div></div>
                    </div>
                    <span class="text-xs">{{ dev.ram }}%</span>
                    {% else %}—{% endif %}
                </td>
                <td><span class="pill pill-{{ dev.status_color }}">{{ dev.status_label }}</span></td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
    {% endif %}

    {% if incidents %}
    <div class="avoid-break">
        <div class="section-header">
            <h2 class="section-title">Incidentes Resueltos</h2>
            <div class="section-subtitle">Detalle de atenciones y tickets cerrados durante {{ month_name|title }}</div>
        </div>

        <table class="data-table">
            <thead>
                <tr>
                    <th style="width: 12%">Fecha</th>
                    <th style="width: 50%">Título / Descripción</th>
                    <th style="width: 18%">Severidad</th>
                    <th style="width: 20%">Equipo Afectado</th>
                </tr>
            </thead>
            <tbody>
                {% for inc in incidents %}
                <tr>
                    <td class="text-slate-500">{{ inc.date }}</td>
                    <td class="font-bold">{{ inc.title }}</td>
                    <td><span class="pill pill-{{ inc.sev_color }}">{{ inc.sev_label }}</span></td>
                    <td class="text-slate-500">{{ inc.device }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    {% if domains %}
    <div class="avoid-break">
        <div class="section-header">
            <h2 class="section-title">Estado de Dominios</h2>
            <div class="section-subtitle">{{ domains|length }} dominios gestionados</div>
        </div>

        <table class="data-table">
            <thead>
                <tr>
                    <th style="width: 30%">Dominio (FQDN)</th>
                    <th style="width: 20%">Registrador</th>
                    <th style="width: 15%">Vencimiento</th>
                    <th style="width: 20%">Días Restantes</th>
                    <th style="width: 15%">Estado</th>
                </tr>
            </thead>
            <tbody>
                {% for dom in domains %}
                <tr>
                    <td class="font-bold">{{ dom.fqdn }}</td>
                    <td class="text-slate-500">{{ dom.registrar }}</td>
                    <td class="text-slate-500">{{ dom.expiry }}</td>
                    <td class="font-bold text-{{ dom.days_color }}">{{ dom.days_str }}</td>
                    <td><span class="pill pill-{{ dom.status_color }}">{{ dom.status_label }}</span></td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

    {% if licenses %}
    <div class="avoid-break">
        <div class="section-header">
            <h2 class="section-title">Licencias Microsoft 365</h2>
            <div class="section-subtitle">Estado de asignación en tenant corporativo</div>
        </div>

        <table class="data-table">
            <thead>
                <tr>
                    <th style="width: 35%">Producto</th>
                    <th class="text-center" style="width: 12%">Total</th>
                    <th class="text-center" style="width: 12%">Usadas</th>
                    <th class="text-center" style="width: 16%">Disponibles</th>
                    <th style="width: 25%">Utilización</th>
                </tr>
            </thead>
            <tbody>
                {% for lic in licenses %}
                <tr>
                    <td class="font-bold">{{ lic.name }}</td>
                    <td class="text-center text-slate-500">{{ lic.total }}</td>
                    <td class="text-center text-slate-800 font-bold">{{ lic.used }}</td>
                    <td class="text-center font-bold text-{{ lic.avail_color }}">{{ lic.available }}</td>
                    <td>
                        <div class="progress-wrapper" style="width: 60px;">
                            <div class="progress-track"><div class="progress-fill" style="width: {{ lic.pct }}%; background-color: {{ lic.bar_color }};"></div></div>
                        </div>
                        <span class="text-xs">{{ lic.pct }}%</span>
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    {% endif %}

</body>
</html>
"""

# ── Helpers de formato de contexto ────────────────────────────────────────────

def format_devices(devices_qs):
    ctx_list = []
    for dev in devices_qs:
        snap = dev.snapshots.first()
        cpu = snap.cpu_percent if snap else None
        ram = snap.ram_used_percent if snap else None
        
        st = dev.status
        st_color = {"online": "green", "warning": "amber", "offline": "red", "never": "slate"}.get(st, "slate")
        st_label = {"online": "En línea", "warning": "Alerta", "offline": "Offline", "never": "Sin datos"}.get(st, st)

        ctx_list.append({
            "name": dev.display_name,
            "type": dev.get_device_type_display(),
            "os": dev.os or "—",
            "cpu": round(cpu, 1) if cpu is not None else None,
            "cpu_color": "#10b981" if cpu and cpu < 70 else "#f59e0b" if cpu and cpu < 90 else "#ef4444",
            "ram": round(ram, 1) if ram is not None else None,
            "ram_color": "#10b981" if ram and ram < 70 else "#f59e0b" if ram and ram < 90 else "#ef4444",
            "status_color": st_color,
            "status_label": st_label
        })
    return ctx_list

def format_incidents(incidents_qs):
    ctx_list = []
    for inc in incidents_qs[:20]:
        sev_color = {"low": "slate", "medium": "blue", "high": "amber", "critical": "red"}.get(inc.severity, "slate")
        ctx_list.append({
            "date": inc.resolved_at.strftime("%d/%m/%y") if inc.resolved_at else "—",
            "title": inc.title[:65],
            "sev_color": sev_color,
            "sev_label": inc.get_severity_display(),
            "device": inc.device.display_name if inc.device else "—"
        })
    return ctx_list

def format_domains(domains_qs):
    ctx_list = []
    for d in domains_qs:
        days = d.days_until_expiry
        if days is None:
            days_str, days_color = "—", "slate-500"
        elif days < 0:
            days_str, days_color = "Vencido", "red"
        elif days < 30:
            days_str, days_color = f"{days} días", "red"
        elif days < 90:
            days_str, days_color = f"{days} días", "amber"
        else:
            days_str, days_color = f"{days} días", "green"

        st_color = {"ok": "green", "warning": "amber", "critical": "red", "expired": "red"}.get(d.status, "slate")
        st_label = {"ok": "OK", "warning": "Por vencer", "critical": "Crítico", "expired": "Vencido", "unknown": "—"}.get(d.status, d.status)
        
        ctx_list.append({
            "fqdn": d.fqdn,
            "registrar": d.registrar or "—",
            "expiry": d.expiry_date.strftime("%d/%m/%Y") if d.expiry_date else "—",
            "days_str": days_str,
            "days_color": days_color,
            "status_color": st_color,
            "status_label": st_label
        })
    return ctx_list

def format_licenses(licenses_qs):
    ctx_list = []
    for l in licenses_qs:
        pct = l.utilization_percent
        bar_color = "#ef4444" if pct >= 100 else "#f59e0b" if pct >= 85 else "#2563eb"
        avail_color = "red" if l.available_licenses == 0 else "green"
        
        ctx_list.append({
            "name": l.friendly_name or l.sku_part_number,
            "total": l.total_licenses,
            "used": l.consumed_licenses,
            "available": l.available_licenses,
            "avail_color": avail_color,
            "pct": pct,
            "bar_color": bar_color
        })
    return ctx_list

# ── Función principal ─────────────────────────────────────────────────────────

def build_report_pdf(client, year: int, month: int) -> tuple[bytes, dict]:
    from core.models import TelemetrySnapshot
    from dateutil.relativedelta import relativedelta
    from django.conf import settings

    period_start = timezone.make_aware(datetime(year, month, 1))
    period_end   = period_start + relativedelta(months=1)
    month_name   = MESES.get(month, str(month))

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    # Queries
    devices           = client.devices.filter(is_active=True).prefetch_related("snapshots")
    incidents_res     = client.incidents.filter(resolved_at__range=(period_start, period_end), is_resolved=True)
    incidents_open    = client.incidents.filter(is_resolved=False)
    domains           = client.domains.all()
    
    try:
        licenses_qs = client.m365_licenses.filter(capability_status="Enabled", total_licenses__lt=10000, total_licenses__gt=0)
    except Exception:
        licenses_qs = []

    # Cálculos
    total_snaps  = TelemetrySnapshot.objects.filter(device__client=client, captured_at__range=(period_start, period_end)).count()
    online_snaps = TelemetrySnapshot.objects.filter(device__client=client, captured_at__range=(period_start, period_end), uptime_seconds__gt=0).count()
    avg_uptime = round(online_snaps / total_snaps * 100, 1) if total_snaps else 0.0

    summary = {
        "period":             f"{year}/{month:02d}",
        "devices_count":      devices.count(),
        "incidents_resolved": incidents_res.count(),
        "incidents_open":     incidents_open.count(),
        "avg_uptime_percent": avg_uptime,
        "domains_critical":   domains.filter(status__in=["critical","expired"]).count(),
    }

    # Renderizado con WeasyPrint y Templates de Django
    context = Context({
        "client": client,
        "company": company,
        "support": support,
        "month_name": month_name,
        "year": year,
        "now_str": timezone.now().strftime("%d/%m/%Y %H:%M"),
        "uptime": avg_uptime,
        "devices_count": devices.count(),
        "inc_ok": incidents_res.count(),
        "inc_open": incidents_open.count(),
        "dom_crit": summary["domains_critical"],
        
        "devices": format_devices(devices),
        "incidents": format_incidents(incidents_res),
        "domains": format_domains(domains),
        "licenses": format_licenses(licenses_qs),
    })

    template = Template(REPORT_TEMPLATE)
    html_string = template.render(context)
    
    # Generar PDF
    pdf_bytes = HTML(string=html_string).write_pdf()
    
    return pdf_bytes, summary