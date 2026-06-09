"""
Sentinel XO — Generador de Reportes PDF
Usa ReportLab puro — sin dependencias de sistema externas.
"""
import io
from datetime import datetime
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
)
from reportlab.graphics.shapes import Drawing, Rect

PAGE_W, PAGE_H = A4
M  = 1.5 * cm
CW = PAGE_W - 2 * M

# ── Paleta ────────────────────────────────────────────────────────────────────
BLUE     = colors.HexColor("#2563eb")
SLATE900 = colors.HexColor("#0f172a")
SLATE800 = colors.HexColor("#1e293b")
SLATE500 = colors.HexColor("#64748b")
SLATE300 = colors.HexColor("#cbd5e1")
SLATE100 = colors.HexColor("#f1f5f9")
SLATE50  = colors.HexColor("#f8fafc")
WHITE    = colors.white
GREEN    = colors.HexColor("#10b981")
AMBER    = colors.HexColor("#f59e0b")
RED      = colors.HexColor("#ef4444")

MESES = {1:"enero",2:"febrero",3:"marzo",4:"abril",5:"mayo",6:"junio",
         7:"julio",8:"agosto",9:"septiembre",10:"octubre",11:"noviembre",12:"diciembre"}

def hx(c):
    """Extrae hex limpio de un color ReportLab."""
    return c.hexval()[2:]

def sty(name, **kw):
    d = dict(fontName="Helvetica", fontSize=9, textColor=SLATE500,
             leading=13, spaceAfter=0, spaceBefore=0)
    d.update(kw)
    return ParagraphStyle(name, **d)

def bar(pct, w=3*cm, h=5, fc=None):
    pct = max(0, min(100, pct))
    if fc is None:
        fc = GREEN if pct < 70 else AMBER if pct < 90 else RED
    d = Drawing(w, h + 4)
    d.add(Rect(0, 2, w, h, fillColor=SLATE100, strokeColor=None, rx=2, ry=2))
    if pct > 0:
        d.add(Rect(0, 2, w * pct / 100, h, fillColor=fc, strokeColor=None, rx=2, ry=2))
    return d

def section_hdr(title, sub=""):
    txt = f'<b>{title.upper()}</b>'
    if sub:
        txt += f'&nbsp;&nbsp;<font color="#94a3b8" size="8">{sub}</font>'
    row = [["", Paragraph(txt, sty("sh", fontName="Helvetica-Bold", fontSize=8,
                                    textColor=BLUE, letterSpacing=0.5))]]
    t = Table(row, colWidths=[3, CW - 3])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(0,0), BLUE),
        ("LEFTPADDING",   (0,0),(-1,-1), 0),
        ("RIGHTPADDING",  (0,0),(-1,-1), 0),
        ("LEFTPADDING",   (1,0),(1,0), 10),
        ("TOPPADDING",    (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    return [t, Spacer(1, 7)]

def tbl_style():
    return TableStyle([
        ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ("RIGHTPADDING",  (0,0),(-1,-1), 10),
        ("TOPPADDING",    (0,0),(-1,-1), 7),
        ("BOTTOMPADDING", (0,0),(-1,-1), 7),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("GRID",          (0,0),(-1,-1), 0.3, SLATE300),
        ("BACKGROUND",    (0,0),(-1,0), SLATE800),
        ("TEXTCOLOR",     (0,0),(-1,0), WHITE),
        ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
        ("FONTSIZE",      (0,0),(-1,0), 8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [WHITE, SLATE50]),
    ])

def th(txt):
    return Paragraph(f'<b>{txt}</b>',
        sty(f"th{txt[:3]}", fontName="Helvetica-Bold", fontSize=8, textColor=WHITE))

def footer(canvas, doc):
    from django.conf import settings
    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")
    canvas.saveState()
    canvas.setStrokeColor(SLATE300)
    canvas.setLineWidth(0.4)
    canvas.line(M, 1.4*cm, PAGE_W - M, 1.4*cm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(SLATE500)
    canvas.drawString(M, 0.9*cm, f"{company}  ·  {support}  ·  Confidencial")
    canvas.drawRightString(PAGE_W - M, 0.9*cm, f"Página {doc.page}")
    canvas.restoreState()


def build_report_pdf(client, year: int, month: int) -> tuple[bytes, dict]:
    from core.models import TelemetrySnapshot
    from dateutil.relativedelta import relativedelta
    from django.conf import settings

    period_start = timezone.make_aware(datetime(year, month, 1))
    period_end   = period_start + relativedelta(months=1)
    month_name   = MESES.get(month, str(month)).capitalize()
    company      = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support      = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    devices        = client.devices.filter(is_active=True).prefetch_related("snapshots")
    incidents_res  = client.incidents.filter(resolved_at__range=(period_start, period_end), is_resolved=True)
    incidents_open = client.incidents.filter(is_resolved=False)
    domains        = client.domains.all()
    try:
        licenses_qs = client.m365_licenses.filter(
            capability_status="Enabled", total_licenses__lt=10000, total_licenses__gt=0)
    except Exception:
        licenses_qs = []

    total_snaps  = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__range=(period_start, period_end)).count()
    online_snaps = TelemetrySnapshot.objects.filter(
        device__client=client, captured_at__range=(period_start, period_end),
        uptime_seconds__gt=0).count()
    avg_uptime = round(online_snaps / total_snaps * 100, 1) if total_snaps else 0.0

    summary = {
        "period":             f"{year}/{month:02d}",
        "devices_count":      devices.count(),
        "incidents_resolved": incidents_res.count(),
        "incidents_open":     incidents_open.count(),
        "avg_uptime_percent": avg_uptime,
        "domains_critical":   domains.filter(status__in=["critical","expired"]).count(),
    }

    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=M, rightMargin=M,
                              topMargin=M, bottomMargin=2*cm,
                              title=f"Reporte {month_name} {year} — {client.company_name}",
                              author=company)
    story = []

    # ── PORTADA ────────────────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph(f'<font color="white" size="18"><b>{company}</b></font>',
                  sty("ch", fontName="Helvetica-Bold", fontSize=18, textColor=WHITE, leading=22)),
        Paragraph(
            f'<font color="#93c5fd" size="9">Reporte de Mantenimiento Preventivo</font><br/>'
            f'<font color="white" size="18"><b>{month_name} {year}</b></font>',
            sty("cs", fontSize=9, textColor=colors.HexColor("#93c5fd"),
                leading=22, alignment=TA_RIGHT)),
    ]], colWidths=[CW * 0.55, CW * 0.45])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), SLATE900),
        ("LEFTPADDING",   (0,0),(-1,-1), 18),
        ("RIGHTPADDING",  (0,0),(-1,-1), 18),
        ("TOPPADDING",    (0,0),(-1,-1), 18),
        ("BOTTOMPADDING", (0,0),(-1,-1), 18),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    story.append(hdr)

    accent = Drawing(CW, 3)
    accent.add(Rect(0, 0, CW, 3, fillColor=BLUE, strokeColor=None))
    story.append(accent)

    info = Table([[
        Paragraph(f'<font size="7" color="#64748b">CLIENTE</font><br/>'
                  f'<font size="13"><b>{client.company_name}</b></font>',
                  sty("ci1", leading=18)),
        Paragraph(f'<font size="7" color="#64748b">CONTACTO</font><br/>'
                  f'<font size="9">{client.contact_email}</font>',
                  sty("ci2", leading=16)),
        Paragraph(f'<font size="7" color="#64748b">PLAN</font><br/>'
                  f'<font size="9"><b>{client.get_plan_display()}</b></font>',
                  sty("ci3", leading=16)),
        Paragraph(f'<font size="7" color="#64748b">GENERADO</font><br/>'
                  f'<font size="9">{timezone.now().strftime("%d/%m/%Y %H:%M")}</font>',
                  sty("ci4", leading=16, alignment=TA_RIGHT)),
    ]], colWidths=[CW*0.30, CW*0.28, CW*0.18, CW*0.24])
    info.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), SLATE50),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ("TOPPADDING",    (0,0),(-1,-1), 11),
        ("BOTTOMPADDING", (0,0),(-1,-1), 11),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("LINEAFTER",     (0,0),(2,0), 0.4, SLATE300),
        ("LINEBELOW",     (0,0),(-1,-1), 2, BLUE),
    ]))
    story.append(info)
    story.append(Spacer(1, 14))

    # ── KPIs ───────────────────────────────────────────────────────────────────
    story += section_hdr("Resumen Ejecutivo")
    up_col = GREEN if avg_uptime >= 99 else AMBER if avg_uptime >= 95 else RED
    op_col = RED if incidents_open.count() > 0 else GREEN
    cr_col = RED if summary["domains_critical"] > 0 else GREEN

    def kpi(lbl, val, sub, vc):
        return Table([[
            Paragraph(f'<font size="7" color="#94a3b8"><b>{lbl}</b></font>',
                      sty(f"kl{lbl[:3]}", fontSize=7, fontName="Helvetica-Bold",
                          textColor=SLATE500, letterSpacing=0.3)),
            Paragraph(f'<font size="22"><b>{val}</b></font>',
                      sty(f"kv{lbl[:3]}", fontName="Helvetica-Bold", fontSize=22,
                          textColor=vc, leading=26)),
            Paragraph(f'<font size="8" color="#94a3b8">{sub}</font>',
                      sty(f"ks{lbl[:3]}", fontSize=8, textColor=SLATE500)),
        ]], colWidths=[None])

    krow = Table([[
        kpi("DISPONIBILIDAD", f"{avg_uptime}%", "promedio del período", up_col),
        kpi("EQUIPOS", str(devices.count()), "monitorizados", BLUE),
        kpi("INCIDENTES RES.", str(incidents_res.count()), "este mes", GREEN),
        kpi("PENDIENTES", str(incidents_open.count()), "sin resolver", op_col),
        kpi("DOM. CRÍTICOS", str(summary["domains_critical"]), "requieren atención", cr_col),
    ]], colWidths=[CW/5]*5)
    krow.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), SLATE50),
        ("LINEAFTER",     (0,0),(3,0), 0.4, SLATE300),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ("TOPPADDING",    (0,0),(-1,-1), 12),
        ("BOTTOMPADDING", (0,0),(-1,-1), 12),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
        ("LINEBELOW",     (0,0),(-1,-1), 2.5, BLUE),
    ]))
    story.append(krow)
    story.append(Spacer(1, 14))

    # ── DISPOSITIVOS ───────────────────────────────────────────────────────────
    if devices.exists():
        story += section_hdr("Estado de Dispositivos",
                              f"{devices.count()} equipo{'s' if devices.count()!=1 else ''}")
        cols = [4.5*cm, 2.5*cm, 3.2*cm, 2.8*cm, 2.8*cm, 2.7*cm]
        rows = [[th("Equipo"), th("Tipo"), th("Sistema"), th("CPU"), th("RAM"), th("Estado")]]
        for dev in devices:
            snap = dev.snapshots.first()
            cpu  = snap.cpu_percent if snap else None
            ram  = snap.ram_used_percent if snap else None
            st   = dev.status
            sc   = {"online":GREEN,"warning":AMBER,"offline":RED,"never":SLATE500}.get(st, SLATE500)
            sl   = {"online":"En línea","warning":"Alerta","offline":"Offline","never":"Sin datos"}.get(st, st)
            rows.append([
                Paragraph(f"<b>{dev.display_name}</b>",
                          sty("dn", fontName="Helvetica-Bold", fontSize=9, textColor=SLATE800)),
                Paragraph(dev.get_device_type_display(),
                          sty("dt", fontSize=8, textColor=SLATE500)),
                Paragraph(dev.os or "—", sty("dos", fontSize=8, textColor=SLATE500)),
                [bar(cpu or 0, w=2.2*cm,
                     fc=GREEN if (cpu or 0)<70 else AMBER if (cpu or 0)<90 else RED),
                 Paragraph(f"{cpu:.1f}%" if cpu is not None else "—",
                           sty("dc", fontSize=8, textColor=SLATE500))]
                if cpu is not None else
                Paragraph("—", sty("dcn", fontSize=8, textColor=SLATE500)),
                [bar(ram or 0, w=2.2*cm,
                     fc=GREEN if (ram or 0)<70 else AMBER if (ram or 0)<90 else RED),
                 Paragraph(f"{ram:.1f}%" if ram is not None else "—",
                           sty("dr", fontSize=8, textColor=SLATE500))]
                if ram is not None else
                Paragraph("—", sty("drn", fontSize=8, textColor=SLATE500)),
                Paragraph(f'<font color="#{hx(sc)}" size="8"><b>{sl}</b></font>',
                          sty("ds", fontName="Helvetica-Bold", fontSize=8, textColor=sc)),
            ])
        t = Table(rows, colWidths=cols, repeatRows=1)
        t.setStyle(tbl_style())
        story.append(t)
        story.append(Spacer(1, 12))

    # ── INCIDENTES ─────────────────────────────────────────────────────────────
    if incidents_res.exists():
        story += section_hdr(f"Incidentes Resueltos — {month_name}",
                              f"{incidents_res.count()} incidente(s)")
        sev_colors = {"low":SLATE500,"medium":BLUE,"high":AMBER,"critical":RED}
        rows = [[th("Fecha"), th("Título"), th("Severidad"), th("Equipo")]]
        for inc in incidents_res[:20]:
            sc = sev_colors.get(inc.severity, SLATE500)
            rows.append([
                Paragraph(inc.resolved_at.strftime("%d/%m/%y") if inc.resolved_at else "—",
                          sty("id", fontSize=8, textColor=SLATE500)),
                Paragraph(inc.title[:65], sty("it", fontSize=9, textColor=SLATE800)),
                Paragraph(f'<font color="#{hx(sc)}" size="8"><b>{inc.get_severity_display()}</b></font>',
                          sty("is", fontName="Helvetica-Bold", fontSize=8, textColor=sc)),
                Paragraph(inc.device.display_name if inc.device else "—",
                          sty("ie", fontSize=8, textColor=SLATE500)),
            ])
        t = Table(rows, colWidths=[2.3*cm, 8.5*cm, 2.5*cm, 3.2*cm], repeatRows=1)
        t.setStyle(tbl_style())
        story.append(t)
        story.append(Spacer(1, 12))

    # ── DOMINIOS ───────────────────────────────────────────────────────────────
    if domains.exists():
        story += section_hdr("Estado de Dominios", f"{domains.count()} dominio(s)")
        rows = [[th("Dominio"), th("Registrador"), th("Vencimiento"),
                 th("Días restantes"), th("Estado")]]
        for d in domains:
            days = d.days_until_expiry
            if days is None:    ds, dc = "—", SLATE500
            elif days < 0:      ds, dc = "Vencido", RED
            elif days < 30:     ds, dc = f"{days} días", RED
            elif days < 90:     ds, dc = f"{days} días", AMBER
            else:               ds, dc = f"{days} días", GREEN
            sc = {"ok":GREEN,"warning":AMBER,"critical":RED,"expired":RED}.get(d.status, SLATE500)
            sl = {"ok":"OK","warning":"Por vencer","critical":"Crítico",
                  "expired":"Vencido","unknown":"—"}.get(d.status, d.status)
            rows.append([
                Paragraph(f"<b>{d.fqdn}</b>",
                          sty("df", fontName="Helvetica-Bold", fontSize=9, textColor=SLATE800)),
                Paragraph(d.registrar or "—", sty("dr", fontSize=8, textColor=SLATE500)),
                Paragraph(d.expiry_date.strftime("%d/%m/%Y") if d.expiry_date else "—",
                          sty("dv", fontSize=8, textColor=SLATE500)),
                Paragraph(f'<font color="#{hx(dc)}" size="9"><b>{ds}</b></font>',
                          sty("dd", fontName="Helvetica-Bold", fontSize=9, textColor=dc)),
                Paragraph(f'<font color="#{hx(sc)}" size="8"><b>{sl}</b></font>',
                          sty("ds2", fontName="Helvetica-Bold", fontSize=8, textColor=sc)),
            ])
        t = Table(rows, colWidths=[5.5*cm, 3*cm, 2.8*cm, 3*cm, 2.2*cm], repeatRows=1)
        t.setStyle(tbl_style())
        story.append(t)
        story.append(Spacer(1, 12))

    # ── LICENCIAS M365 ─────────────────────────────────────────────────────────
    if licenses_qs:
        story += section_hdr("Licencias Microsoft 365",
                              f"{len(list(licenses_qs))} producto(s)")
        rows = [[th("Producto"), th("Total"), th("Usadas"), th("Disponibles"), th("Utilización")]]
        for l in licenses_qs:
            pct   = l.utilization_percent
            bc    = RED if pct >= 100 else AMBER if pct >= 85 else BLUE
            avc   = RED if l.available_licenses == 0 else GREEN
            rows.append([
                Paragraph(f"<b>{l.friendly_name or l.sku_part_number}</b>",
                          sty("ln", fontName="Helvetica-Bold", fontSize=9, textColor=SLATE800)),
                Paragraph(str(l.total_licenses),
                          sty("lt", fontSize=9, textColor=SLATE500, alignment=TA_CENTER)),
                Paragraph(str(l.consumed_licenses),
                          sty("lc", fontSize=9, textColor=SLATE800, alignment=TA_CENTER)),
                Paragraph(f'<font color="#{hx(avc)}" size="9"><b>{l.available_licenses}</b></font>',
                          sty("la", fontName="Helvetica-Bold", fontSize=9,
                              textColor=avc, alignment=TA_CENTER)),
                [bar(pct, w=3.2*cm, fc=bc),
                 Paragraph(f"{pct}%", sty("lp", fontSize=8, textColor=SLATE500))],
            ])
        ts = tbl_style()
        ts.add("ALIGN", (1,1), (3,-1), "CENTER")
        t = Table(rows, colWidths=[6*cm, 2*cm, 2*cm, 2.5*cm, 4*cm], repeatRows=1)
        t.setStyle(ts)
        story.append(t)

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    pdf = buf.getvalue()
    buf.close()
    return pdf, summary
