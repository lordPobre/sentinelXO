"""
Sentinel XO — Generador de Reporte Mensual de Mantenimiento (PDF)
=================================================================
Reconstruido sobre `reports.pdf_theme` (sistema de diseño compartido).

- `build_report_pdf(client, year, month)` → recopila datos del ORM y arma el PDF.
- `compose_monthly_story(data)` → capa de presentación PURA (sin Django); recibe
  un dict de primitivos. Esto permite previsualizar el diseño con datos ficticios.
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Spacer, PageBreak

from reports import pdf_theme as T


# ── Mapas de presentación ────────────────────────────────────────────────────
_SEV_PILL = {"low": "slate", "medium": "blue", "high": "amber", "critical": "red"}
_DEV_PILL = {"online": "green", "warning": "amber", "offline": "red", "never": "slate"}
_DEV_LBL  = {"online": "En línea", "warning": "Alerta", "offline": "Offline", "never": "Sin datos"}
_DOM_PILL = {"ok": "green", "warning": "amber", "critical": "red", "expired": "red"}
_DOM_LBL  = {"ok": "OK", "warning": "Por vencer", "critical": "Crítico", "expired": "Vencido", "unknown": "—"}


# ════════════════════════════════════════════════════════════════════════════
#  COMPOSICIÓN (pura — sin Django)
# ════════════════════════════════════════════════════════════════════════════
def compose_monthly_story(d: dict) -> list:
    story = []

    # ── Header ───────────────────────────────────────────────────────────────
    story += T.header_band(
        company=d["company"],
        kicker="Reporte de Mantenimiento Preventivo",
        title=f'{d["month_name"]} {d["year"]}',
        meta=None,
    )

    # ── Info cliente ─────────────────────────────────────────────────────────
    story.append(T.info_strip([
        ("Cliente",  d["client_name"], True),
        ("Contacto", d["client_email"]),
        ("Plan",     d["plan"]),
        ("Generado", d["generated_at"]),
    ]))
    story.append(T.gap(20))

    # ── Resumen ejecutivo (KPIs) ─────────────────────────────────────────────
    k = d["kpis"]
    up = k["uptime"]
    up_col  = T.GREEN if (up or 0) >= 99 else (T.AMBER if (up or 0) >= 95 else T.RED)
    op_col  = T.RED if k["inc_open"] > 0 else T.TEXT
    dom_col = T.RED if k["domains_critical"] > 0 else T.GREEN

    story += T.section("Resumen Ejecutivo", "Métricas clave del período de facturación")
    story.append(T.kpi_cards([
        ("Disponibilidad", f"{up:g}%" if up is not None else "—", "promedio del período", up_col),
        ("Equipos",        str(k["devices"]),         "monitorizados", T.BRAND),
        ("Incidentes res.",str(k["inc_resolved"]),    "resueltos este mes", T.GREEN),
        ("Pendientes",     str(k["inc_open"]),        "requieren atención", op_col),
        ("Dom. críticos",  str(k["domains_critical"]),"por vencer", dom_col),
    ]))
    story.append(T.gap(18))

    # ── Resumen narrativo IA ─────────────────────────────────────────────────
    if d.get("narrative"):
        story.append(T.callout("Resumen del período · IA", d["narrative"]))
        story.append(T.gap(18))

    # ── Dispositivos ─────────────────────────────────────────────────────────
    devs = d["devices"]
    story += T.section("Estado de Dispositivos",
                       f"{len(devs)} equipo{'s' if len(devs) != 1 else ''} monitorizado{'s' if len(devs) != 1 else ''}")
    if devs:
        rows = [[T.th("Equipo"), T.th("Tipo"), T.th("Sistema"),
                 T.th("CPU prom."), T.th("RAM prom."), T.th("Estado", TA_CENTER)]]
        for x in devs:
            cpu, ram = x["cpu"], x["ram"]
            cpu_cell = T.progress(cpu, T.status_color(cpu), width=52) if cpu is not None else T.td("—", color=T.FAINT)
            ram_cell = T.progress(ram, T.status_color(ram), width=52) if ram is not None else T.td("—", color=T.FAINT)
            rows.append([
                T.td(x["name"], bold=True),
                T.td(x["type"], color=T.MUTED, size=8),
                T.td(x["os"] or "—", color=T.MUTED, size=8),
                cpu_cell, ram_cell,
                T.pill(_DEV_LBL.get(x["status"], x["status"]), _DEV_PILL.get(x["status"], "slate")),
            ])
        story.append(T.table(
            rows,
            col_widths=[T.CW*0.22, T.CW*0.17, T.CW*0.16, T.CW*0.14, T.CW*0.16, T.CW*0.15],
            aligns={5: "C"},
        ))
    else:
        story.append(T.empty("Sin dispositivos registrados en este período."))
    story.append(T.gap(18))

    # ── Incidentes ───────────────────────────────────────────────────────────
    incs = d["incidents"]
    story += T.section("Incidentes Resueltos",
                       f"Atenciones cerradas durante {d['month_name']}")
    if incs:
        rows = [[T.th("Fecha"), T.th("Título / Descripción"),
                 T.th("Severidad", TA_CENTER), T.th("Equipo afectado")]]
        for x in incs:
            rows.append([
                T.td(x["date"], color=T.MUTED, mono=True, size=8),
                T.td(x["title"][:70], bold=True),
                T.pill(x["sev_label"], _SEV_PILL.get(x["severity"], "slate")),
                T.td(x["device"] or "—", color=T.MUTED),
            ])
        story.append(T.table(
            rows,
            col_widths=[T.CW*0.13, T.CW*0.52, T.CW*0.16, T.CW*0.19],
            aligns={2: "C"},
        ))
    else:
        story.append(T.empty("No hubo incidentes resueltos en este período."))
    story.append(T.gap(18))

    # ── Dominios ─────────────────────────────────────────────────────────────
    doms = d["domains"]
    if doms:
        story += T.section("Estado de Dominios",
                           f"{len(doms)} dominio{'s' if len(doms) != 1 else ''} gestionado{'s' if len(doms) != 1 else ''}")
        rows = [[T.th("Dominio (FQDN)"), T.th("Registrador"), T.th("Vencimiento"),
                 T.th("Días", TA_CENTER), T.th("Estado", TA_CENTER)]]
        for x in doms:
            days = x["days"]
            if days is None:   ds, dc = "—", T.MUTED
            elif days < 0:     ds, dc = "Vencido", T.RED
            elif days < 30:    ds, dc = f"{days}d", T.RED
            elif days < 90:    ds, dc = f"{days}d", T.AMBER
            else:              ds, dc = f"{days}d", T.GREEN
            rows.append([
                T.td(x["fqdn"], bold=True),
                T.td(x["registrar"] or "—", color=T.MUTED),
                T.td(x["expiry"] or "—", color=T.MUTED, mono=True, size=8),
                T.td(ds, bold=True, color=dc, align=TA_CENTER),
                T.pill(_DOM_LBL.get(x["status"], x["status"]), _DOM_PILL.get(x["status"], "slate")),
            ])
        story.append(T.table(
            rows,
            col_widths=[T.CW*0.30, T.CW*0.20, T.CW*0.18, T.CW*0.12, T.CW*0.20],
            aligns={3: "C", 4: "C"},
        ))
        story.append(T.gap(18))

    # ── Licencias M365 ───────────────────────────────────────────────────────
    lics = d["licenses"]
    if lics:
        story.append(PageBreak())
        story += T.section("Licencias Microsoft 365", "Estado de asignación en el tenant corporativo")
        rows = [[T.th("Producto"), T.th("Total", TA_CENTER), T.th("Usadas", TA_CENTER),
                 T.th("Disponibles", TA_CENTER), T.th("Utilización")]]
        for x in lics:
            pct = x["pct"]
            bar_col = T.RED if pct >= 100 else (T.AMBER if pct >= 85 else T.BRAND)
            av_col = T.RED if x["available"] == 0 else T.GREEN
            rows.append([
                T.td(x["name"], bold=True),
                T.td(x["total"], color=T.MUTED, align=TA_CENTER, mono=True),
                T.td(x["consumed"], bold=True, align=TA_CENTER, mono=True),
                T.td(x["available"], bold=True, color=av_col, align=TA_CENTER, mono=True),
                T.progress(pct, bar_col, width=72),
            ])
        story.append(T.table(
            rows,
            col_widths=[T.CW*0.34, T.CW*0.12, T.CW*0.12, T.CW*0.16, T.CW*0.26],
            aligns={1: "C", 2: "C", 3: "C"},
        ))

    return story


def _render(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=T.ML, rightMargin=T.MR,
                            topMargin=T.MT, bottomMargin=T.MB)
    footer = T.make_footer(data["company"], data["support"])
    doc.build(compose_monthly_story(data), onFirstPage=footer, onLaterPages=footer)
    pdf = buf.getvalue()
    buf.close()
    return pdf


# ════════════════════════════════════════════════════════════════════════════
#  ENTRADA CON DATOS REALES (Django)
# ════════════════════════════════════════════════════════════════════════════
def build_report_pdf(client, year: int, month: int) -> tuple[bytes, dict]:
    from datetime import datetime
    from django.utils import timezone
    from django.conf import settings
    from dateutil.relativedelta import relativedelta
    from core.models import TelemetrySnapshot

    period_start = timezone.make_aware(datetime(year, month, 1))
    period_end   = period_start + relativedelta(months=1)
    month_name   = T.MESES.get(month, str(month)).capitalize()

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    devices_qs     = client.devices.filter(is_active=True).prefetch_related("snapshots")
    incidents_res  = client.incidents.filter(resolved_at__range=(period_start, period_end), is_resolved=True)
    incidents_open = client.incidents.filter(is_resolved=False)
    domains_qs     = client.domains.all()
    try:
        licenses = list(client.m365_licenses.filter(
            capability_status="Enabled", total_licenses__lt=10000, total_licenses__gt=0))
    except Exception:
        licenses = []

    total_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__range=(period_start, period_end)).count()
    online_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__range=(period_start, period_end),
        uptime_seconds__gt=0).count()
    avg_uptime = round(online_snaps / total_snaps * 100, 1) if total_snaps else 0.0
    domains_critical = domains_qs.filter(status__in=["critical", "expired"]).count()

    # Narrativa IA (best-effort)
    narrative = None
    try:
        from core.views_ai import generate_narrative_summary
        summary_seed = {
            "devices_count": devices_qs.count(),
            "incidents_resolved": incidents_res.count(),
            "incidents_open": incidents_open.count(),
            "avg_uptime_percent": avg_uptime,
            "domains_critical": domains_critical,
        }
        narrative = generate_narrative_summary(client, year, month, summary_seed)
    except Exception:
        narrative = None

    def dev_dict(dev):
        snap = dev.snapshots.first()
        return {
            "name": dev.display_name,
            "type": dev.get_device_type_display(),
            "os": dev.os or "",
            "cpu": round(snap.cpu_percent, 1) if snap else None,
            "ram": round(snap.ram_used_percent, 1) if snap else None,
            "status": dev.status,
        }

    def inc_dict(inc):
        return {
            "date": timezone.localtime(inc.resolved_at).strftime("%d/%m/%y") if inc.resolved_at else "—",
            "title": inc.title,
            "severity": inc.severity,
            "sev_label": inc.get_severity_display(),
            "device": inc.device.display_name if inc.device else "",
        }

    def dom_dict(dm):
        return {
            "fqdn": dm.fqdn,
            "registrar": dm.registrar or "",
            "expiry": dm.expiry_date.strftime("%d/%m/%Y") if dm.expiry_date else "",
            "days": dm.days_until_expiry,
            "status": dm.status,
        }

    def lic_dict(l):
        return {
            "name": l.friendly_name or l.sku_part_number,
            "total": l.total_licenses,
            "consumed": l.consumed_licenses,
            "available": l.available_licenses,
            "pct": l.utilization_percent,
        }

    data = {
        "company": company, "support": support,
        "client_name": client.company_name,
        "client_email": client.contact_email,
        "plan": client.get_plan_display(),
        "generated_at": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
        "month_name": month_name, "year": year, "month": month,
        "kpis": {
            "uptime": avg_uptime,
            "devices": devices_qs.count(),
            "inc_resolved": incidents_res.count(),
            "inc_open": incidents_open.count(),
            "domains_critical": domains_critical,
            "total_snaps": total_snaps,
        },
        "narrative": narrative,
        "devices": [dev_dict(x) for x in devices_qs],
        "incidents": [inc_dict(x) for x in incidents_res[:20]],
        "domains": [dom_dict(x) for x in domains_qs],
        "licenses": [lic_dict(x) for x in licenses],
    }

    summary = {
        "period": f"{year}/{month:02d}",
        "devices_count": data["kpis"]["devices"],
        "incidents_resolved": data["kpis"]["inc_resolved"],
        "incidents_open": data["kpis"]["inc_open"],
        "avg_uptime_percent": avg_uptime,
        "domains_critical": domains_critical,
    }
    return _render(data), summary
