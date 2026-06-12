"""
Sentinel XO — Generador de Reportes PDF
ReportLab puro, diseño idéntico al template WeasyPrint original.
"""
import io
from datetime import datetime
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, PageBreak)
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

PAGE_W, PAGE_H = A4
ML = MR = 15*mm
MT = 15*mm
MB = 22*mm
CW = PAGE_W - ML - MR

# ── Paleta ─────────────────────────────────────────────────────────────────
C_DARK   = colors.HexColor("#0f172a")
C_BLUE   = colors.HexColor("#2563eb")
C_SLATE8 = colors.HexColor("#1e293b")
C_SLATE5 = colors.HexColor("#64748b")
C_SLATE3 = colors.HexColor("#e2e8f0")
C_SLATE1 = colors.HexColor("#f1f5f9")
C_SLATE0 = colors.HexColor("#f8fafc")
C_WHITE  = colors.white
C_GREEN  = colors.HexColor("#10b981")
C_AMBER  = colors.HexColor("#f59e0b")
C_RED    = colors.HexColor("#ef4444")

PILL = {
    "green": (colors.HexColor("#d1fae5"), colors.HexColor("#065f46")),
    "amber": (colors.HexColor("#fef3c7"), colors.HexColor("#92400e")),
    "red":   (colors.HexColor("#fee2e2"), colors.HexColor("#991b1b")),
    "blue":  (colors.HexColor("#dbeafe"), colors.HexColor("#1e40af")),
    "slate": (colors.HexColor("#f1f5f9"), colors.HexColor("#475569")),
}

MESES = {
    1:"enero", 2:"febrero", 3:"marzo", 4:"abril", 5:"mayo", 6:"junio",
    7:"julio", 8:"agosto", 9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre"
}

# ── Helpers ─────────────────────────────────────────────────────────────────
def ps(name, **kw):
    d = dict(fontName="Helvetica", fontSize=9, textColor=C_SLATE5, leading=13)
    d.update(kw)
    return ParagraphStyle(name, **d)

def pill_cell(txt, color_key="slate"):
    bg, fg = PILL.get(color_key, PILL["slate"])
    t = Table([[Paragraph(txt, ps(f"pl_{txt[:6]}",
        fontName="Helvetica-Bold", fontSize=7, textColor=fg,
        leading=9, alignment=TA_CENTER))]],
        colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,0), bg),
        ("LEFTPADDING",   (0,0),(0,0), 7),
        ("RIGHTPADDING",  (0,0),(0,0), 7),
        ("TOPPADDING",    (0,0),(0,0), 3),
        ("BOTTOMPADDING", (0,0),(0,0), 3),
    ]))
    return t

def progress_bar(pct, bar_color, width=50):
    d = Drawing(width, 8)
    d.add(Rect(0, 1, width, 6, fillColor=C_SLATE3, strokeColor=None, rx=3, ry=3))
    if pct > 0:
        d.add(Rect(0, 1, width * min(pct / 100.0, 1), 6,
                   fillColor=bar_color, strokeColor=None, rx=3, ry=3))
    return d

def th(txt, align=TA_LEFT):
    return Paragraph(f"<b>{txt}</b>", ps(f"TH_{txt[:6]}",
        fontName="Helvetica-Bold", fontSize=7.5, textColor=C_WHITE,
        letterSpacing=0.3, leading=10, alignment=align))

def td(txt, bold=False, color=C_SLATE8, size=8.5, align=TA_LEFT):
    return Paragraph(str(txt), ps(f"TD_{txt[:6]}",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, textColor=color, leading=12, alignment=align))

TH_STYLE = [
    ("BACKGROUND",    (0,0), (-1,0),  C_SLATE8),
    ("TEXTCOLOR",     (0,0), (-1,0),  C_WHITE),
    ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
    ("FONTSIZE",      (0,0), (-1,-1), 8.5),
    ("TOPPADDING",    (0,0), (-1,0),  9),
    ("BOTTOMPADDING", (0,0), (-1,0),  9),
    ("TOPPADDING",    (0,1), (-1,-1), 8),
    ("BOTTOMPADDING", (0,1), (-1,-1), 8),
    ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ("RIGHTPADDING",  (0,0), (-1,-1), 10),
    ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_SLATE0]),
    ("LINEBELOW",     (0,0), (-1,-1), 0.4, C_SLATE3),
    ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
]

def section_header(title, subtitle=""):
    inner = Table([
        [Paragraph(f"<b>{title.upper()}</b>", ps(f"SH_{title[:6]}",
            fontName="Helvetica-Bold", fontSize=11, textColor=C_SLATE8, leading=14))],
        [Paragraph(subtitle, ps(f"SS_{title[:6]}",
            fontSize=8, textColor=C_SLATE5, leading=11))],
    ], colWidths=[None])
    t = Table([["", inner]], colWidths=[4, CW - 4])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,0),  C_BLUE),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("LEFTPADDING",   (1,0),(1,0),   10),
        ("TOPPADDING",    (0,0),(-1,-1), 8),
        ("BOTTOMPADDING", (0,0),(-1,-1), 8),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    return [t, Spacer(1, 10)]

def footer_cb(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(C_SLATE5)
    canvas.drawString(ML, 12*mm,
        "Sentinel XO  ·  soporte@perseustechnology.dev  ·  Confidencial")
    canvas.drawRightString(PAGE_W - MR, 12*mm, f"Página {doc.page}")
    canvas.restoreState()


# ── Función principal ────────────────────────────────────────────────────────
def build_report_pdf(client, year: int, month: int) -> tuple[bytes, dict]:
    from core.models import TelemetrySnapshot
    from dateutil.relativedelta import relativedelta
    from django.conf import settings

    period_start = timezone.make_aware(datetime(year, month, 1))
    period_end   = period_start + relativedelta(months=1)
    month_name   = MESES.get(month, str(month)).capitalize()

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    # ── Queries ──────────────────────────────────────────────────────────────
    devices        = client.devices.filter(is_active=True).prefetch_related("snapshots")
    incidents_res  = client.incidents.filter(
        resolved_at__range=(period_start, period_end), is_resolved=True)
    incidents_open = client.incidents.filter(is_resolved=False)
    domains        = client.domains.all()
    try:
        licenses = list(client.m365_licenses.filter(
            capability_status="Enabled",
            total_licenses__lt=10000,
            total_licenses__gt=0,
        ))
    except Exception:
        licenses = []

    total_snaps  = TelemetrySnapshot.objects.filter(
        device__client=client,
        captured_at__range=(period_start, period_end),
    ).count()
    online_snaps = TelemetrySnapshot.objects.filter(
        device__client=client,
        captured_at__range=(period_start, period_end),
        uptime_seconds__gt=0,
    ).count()
    avg_uptime = round(online_snaps / total_snaps * 100, 1) if total_snaps else 0.0

    summary = {
        "period":             f"{year}/{month:02d}",
        "devices_count":      devices.count(),
        "incidents_resolved": incidents_res.count(),
        "incidents_open":     incidents_open.count(),
        "avg_uptime_percent": avg_uptime,
        "domains_critical":   domains.filter(status__in=["critical", "expired"]).count(),
    }

    # ── Documento ────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB)
    story = []

    # ── HEADER FULL-BLEED ────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph(
            f'<font color="white" size="18"><b>{company}</b></font><br/>'
            f'<font color="#cbd5e1" size="9">Plataforma de Monitoreo Avanzado</font>',
            ps("hL", fontName="Helvetica-Bold", fontSize=18,
               textColor=C_WHITE, leading=22)),
        Paragraph(
            f'<font color="#93c5fd" size="9">Reporte de Mantenimiento Preventivo</font><br/>'
            f'<font color="white" size="18"><b>{month_name} {year}</b></font>',
            ps("hR", fontSize=9, textColor=colors.HexColor("#93c5fd"),
               leading=22, alignment=TA_RIGHT)),
    ]], colWidths=[CW * 0.55, CW * 0.45])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_DARK),
        ("LEFTPADDING",   (0,0), (-1,-1), 20),
        ("RIGHTPADDING",  (0,0), (-1,-1), 20),
        ("TOPPADDING",    (0,0), (-1,-1), 20),
        ("BOTTOMPADDING", (0,0), (-1,-1), 20),
        ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(hdr)

    # Accent line
    accent = Drawing(CW, 4)
    accent.add(Rect(0, 0, CW, 4, fillColor=C_BLUE, strokeColor=None))
    story.append(accent)
    story.append(Spacer(1, 4))

    # ── INFO CLIENTE ─────────────────────────────────────────────────────────
    def info_cell(label, value, size=10, bold=True):
        return Table([
            [Paragraph(label, ps(f"il_{label[:4]}",
                fontName="Helvetica-Bold", fontSize=7, textColor=C_SLATE5,
                letterSpacing=0.5, leading=10))],
            [Paragraph(value, ps(f"iv_{value[:4]}",
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=size, textColor=C_SLATE8, leading=size + 4))],
        ], colWidths=[None])

    cli = Table([[
        info_cell("CLIENTE",     client.company_name, size=13),
        info_cell("CONTACTO",    client.contact_email, size=9, bold=False),
        info_cell("PLAN ACTIVO", client.get_plan_display(), size=9),
        info_cell("GENERADO",    timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
                  size=9, bold=False),
    ]], colWidths=[CW*0.32, CW*0.26, CW*0.20, CW*0.22])
    cli.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_SLATE0),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 12),
        ("TOPPADDING",    (0,0), (-1,-1), 12),
        ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ("LINEAFTER",     (0,0), (2,0),   0.5, C_SLATE3),
        ("LINEBELOW",     (0,0), (-1,-1), 3,   C_BLUE),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    story.append(cli)
    story.append(Spacer(1, 22))

    # ── KPIs ─────────────────────────────────────────────────────────────────
    story += section_header("Resumen Ejecutivo",
                             "Métricas clave del período de facturación")

    up_col  = "#10b981" if avg_uptime >= 99 else "#f59e0b" if avg_uptime >= 95 else "#ef4444"
    op_col  = "#ef4444" if incidents_open.count() > 0 else "#1e293b"
    dom_col = "#ef4444" if summary["domains_critical"] > 0 else "#10b981"

    uptime_str = f"{avg_uptime:g}%"

    kpi_data = [
        ("DISPONIBILIDAD", uptime_str,                      "promedio del período",       up_col),
        ("EQUIPOS",         str(devices.count()),            "monitorizados activos",      "#2563eb"),
        ("INCIDENTES RES.", str(incidents_res.count()),      "solucionados este mes",      "#10b981"),
        ("PENDIENTES",      str(incidents_open.count()),     "requieren atención",         op_col),
        ("DOM. CRÍTICOS",   str(summary["domains_critical"]),"sin alertas de expiración",  dom_col),
    ]
    KW = CW / 5
    kpi_cells = []
    for lbl_t, val_t, sub_t, col in kpi_data:
        kpi_cells.append(Table([
            [Paragraph(lbl_t, ps(f"kl_{lbl_t[:4]}", fontName="Helvetica-Bold",
                fontSize=7, textColor=C_SLATE5, letterSpacing=0.3,
                leading=9, alignment=TA_CENTER))],
            [Paragraph(f"<b>{val_t}</b>", ps(f"kv_{lbl_t[:4]}", fontName="Helvetica-Bold",
                fontSize=22, textColor=colors.HexColor(col),
                leading=28, alignment=TA_CENTER))],
            [Paragraph(sub_t, ps(f"ks_{lbl_t[:4]}", fontSize=7.5,
                textColor=C_SLATE5, leading=10, alignment=TA_CENTER))],
        ], colWidths=[KW - 22]))

    kpi_row = Table([kpi_cells], colWidths=[KW] * 5)
    kpi_row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_SLATE0),
        ("LINEAFTER",     (0,0), (3,0),   0.5,  C_SLATE3),
        ("LINEBELOW",     (0,0), (-1,-1), 3,    C_BLUE),
        ("LEFTPADDING",   (0,0), (-1,-1), 11),
        ("RIGHTPADDING",  (0,0), (-1,-1), 11),
        ("TOPPADDING",    (0,0), (-1,-1), 14),
        ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
    ]))
    story.append(kpi_row)
    story.append(Spacer(1, 22))

    # ── RESUMEN NARRATIVO IA ─────────────────────────────────────────────────
    try:
        from core.views_ai import generate_narrative_summary
        narrative = generate_narrative_summary(client, year, month, summary)
    except Exception:
        narrative = None

    if narrative:
        narr_box = Table([[
            Paragraph(
                f'<font color="#2563eb" size="8"><b>🧠 RESUMEN DEL PERÍODO</b></font><br/><br/>'
                f'<font color="#334155" size="9">{narrative}</font>',
                ps("narr", fontSize=9, textColor=C_SLATE8, leading=14,
                   alignment=TA_LEFT)
            )
        ]], colWidths=[CW])
        narr_box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#eff6ff")),
            ("BOX",           (0,0), (-1,-1), 0.5, colors.HexColor("#bfdbfe")),
            ("LEFTPADDING",   (0,0), (-1,-1), 16),
            ("RIGHTPADDING",  (0,0), (-1,-1), 16),
            ("TOPPADDING",    (0,0), (-1,-1), 14),
            ("BOTTOMPADDING", (0,0), (-1,-1), 14),
        ]))
        story.append(narr_box)
        story.append(Spacer(1, 22))

    # ── DISPOSITIVOS ──────────────────────────────────────────────────────────
    if devices.exists():
        story += section_header(
            "Estado de Dispositivos",
            f"{devices.count()} equipo{'s' if devices.count() != 1 else ''} "
            f"registrado{'s' if devices.count() != 1 else ''} y monitorizado{'s' if devices.count() != 1 else ''}")

        dev_rows = [[th("Equipo"), th("Tipo"), th("Sistema"),
                     th("CPU (Promedio)"), th("RAM (Promedio)"), th("Estado")]]

        for dev in devices:
            snap = dev.snapshots.first()
            cpu  = round(snap.cpu_percent, 1) if snap else None
            ram  = round(snap.ram_used_percent, 1) if snap else None

            cpu_c = C_GREEN if cpu and cpu < 70 else C_AMBER if cpu and cpu < 90 else C_RED
            ram_c = C_GREEN if ram and ram < 70 else C_AMBER if ram and ram < 90 else C_RED

            st    = dev.status
            st_key = {"online":"green","warning":"amber","offline":"red","never":"slate"}.get(st,"slate")
            st_lbl = {"online":"En línea","warning":"Alerta","offline":"Offline","never":"Sin datos"}.get(st, st)

            cpu_cell = (Table([[progress_bar(cpu, cpu_c, 50)],
                               [td(f"{cpu}%", size=7.5, color=C_SLATE5)]], colWidths=[None])
                        if cpu is not None else td("—", color=C_SLATE5))
            ram_cell = (Table([[progress_bar(ram, ram_c, 50)],
                               [td(f"{ram}%", size=7.5, color=C_SLATE5)]], colWidths=[None])
                        if ram is not None else td("—", color=C_SLATE5))

            dev_rows.append([
                td(dev.display_name, bold=True),
                td(dev.get_device_type_display(), color=C_SLATE5),
                td(dev.os or "—", color=C_SLATE5),
                cpu_cell,
                ram_cell,
                pill_cell(st_lbl, st_key),
            ])

        t = Table(dev_rows,
                  colWidths=[4.2*cm, 2.4*cm, 2.8*cm, 2.8*cm, 2.8*cm, 2.8*cm],
                  repeatRows=1)
        t.setStyle(TableStyle(TH_STYLE))
        story.append(t)
        story.append(Spacer(1, 18))

    # ── INCIDENTES ────────────────────────────────────────────────────────────
    story += section_header(
        "Incidentes Resueltos",
        f"Detalle de atenciones y tickets cerrados durante {month_name}")

    if incidents_res.exists():
        sev_pill = {"low":"slate","medium":"blue","high":"amber","critical":"red"}
        inc_rows = [[th("Fecha"), th("Título / Descripción"),
                     th("Severidad"), th("Equipo Afectado")]]
        for inc in incidents_res[:20]:
            inc_rows.append([
                td(timezone.localtime(inc.resolved_at).strftime("%d/%m/%y") if inc.resolved_at else "—",
                   color=C_SLATE5),
                td(inc.title[:65], bold=True),
                pill_cell(inc.get_severity_display(),
                          sev_pill.get(inc.severity, "slate")),
                td(inc.device.display_name if inc.device else "—", color=C_SLATE5),
            ])
        t = Table(inc_rows,
                  colWidths=[2.2*cm, 10*cm, 2.8*cm, 3.2*cm],
                  repeatRows=1)
        t.setStyle(TableStyle(TH_STYLE))
        story.append(t)
    else:
        story.append(Paragraph("No hubo incidentes resueltos en este período.",
            ps("noInc", fontSize=9, textColor=C_SLATE5)))
    story.append(Spacer(1, 18))

    # ── DOMINIOS ──────────────────────────────────────────────────────────────
    if domains.exists():
        story += section_header(
            "Estado de Dominios",
            f"{domains.count()} dominio{'s' if domains.count() != 1 else ''} gestionado{'s' if domains.count() != 1 else ''}")

        dom_rows = [[th("Dominio (FQDN)"), th("Registrador"),
                     th("Vencimiento"), th("Días Restantes"), th("Estado")]]
        for d in domains:
            days = d.days_until_expiry
            if days is None:   ds, dc = "—",         C_SLATE5
            elif days < 0:     ds, dc = "Vencido",   C_RED
            elif days < 30:    ds, dc = f"{days} días", C_RED
            elif days < 90:    ds, dc = f"{days} días", C_AMBER
            else:              ds, dc = f"{days} días", C_GREEN

            st_key = {"ok":"green","warning":"amber","critical":"red",
                      "expired":"red"}.get(d.status, "slate")
            st_lbl = {"ok":"OK","warning":"Por vencer","critical":"Crítico",
                      "expired":"Vencido","unknown":"—"}.get(d.status, d.status)

            dom_rows.append([
                td(d.fqdn, bold=True),
                td(d.registrar or "—", color=C_SLATE5),
                td(d.expiry_date.strftime("%d/%m/%Y") if d.expiry_date else "—",
                   color=C_SLATE5),
                td(ds, bold=True, color=dc),
                pill_cell(st_lbl, st_key),
            ])

        t = Table(dom_rows,
                  colWidths=[5.2*cm, 3*cm, 2.8*cm, 3.2*cm, 4*cm],
                  repeatRows=1)
        t.setStyle(TableStyle(TH_STYLE))
        story.append(t)

    # ── LICENCIAS M365 ────────────────────────────────────────────────────────
    if licenses:
        story.append(PageBreak())
        story += section_header(
            "Licencias Microsoft 365",
            "Estado de asignación en tenant corporativo")

        lic_rows = [[th("Producto"), th("Total", TA_CENTER), th("Usadas", TA_CENTER),
                     th("Disponibles", TA_CENTER), th("Utilización")]]
        for l in licenses:
            pct     = l.utilization_percent
            bar_col = C_RED if pct >= 100 else C_AMBER if pct >= 85 else C_BLUE
            av_col  = C_RED if l.available_licenses == 0 else C_GREEN
            pct_str = f"{pct:g}%"

            lic_rows.append([
                td(l.friendly_name or l.sku_part_number, bold=True),
                td(str(l.total_licenses), color=C_SLATE5, align=TA_CENTER),
                td(str(l.consumed_licenses), bold=True, align=TA_CENTER),
                td(str(l.available_licenses), bold=True, color=av_col, align=TA_CENTER),
                Table([[progress_bar(pct, bar_col, 55)],
                       [td(pct_str, size=7.5, color=C_SLATE5)]], colWidths=[None]),
            ])

        ts = TableStyle(TH_STYLE + [("ALIGN", (1,1),(3,-1), "CENTER")])
        t  = Table(lic_rows,
                   colWidths=[7*cm, 2*cm, 2*cm, 2.8*cm, 4.4*cm],
                   repeatRows=1)
        t.setStyle(ts)
        story.append(t)

    doc.build(story, onFirstPage=footer_cb, onLaterPages=footer_cb)
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes, summary
