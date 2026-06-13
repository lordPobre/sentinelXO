"""
Sentinel XO — Reporte PDF de Postura de Seguridad
ReportLab puro, mismo estilo visual que generator.py / device_report.py.
"""
import io
from datetime import datetime
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
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

# ── Paleta (misma que generator.py) ───────────────────────────────────────────
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


# ── Helpers ─────────────────────────────────────────────────────────────────
def ps(name, **kw):
    d = dict(fontName="Helvetica", fontSize=9, textColor=C_SLATE5, leading=13)
    d.update(kw)
    return ParagraphStyle(name, **d)


def pill_cell(txt, color_key="slate"):
    bg, fg = PILL.get(color_key, PILL["slate"])
    t = Table([[Paragraph(txt, ps(f"pl_{txt[:8]}",
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


def progress_bar(pct, bar_color, width=60):
    d = Drawing(width, 8)
    d.add(Rect(0, 1, width, 6, fillColor=C_SLATE3, strokeColor=None, rx=3, ry=3))
    if pct and pct > 0:
        d.add(Rect(0, 1, width * min(pct / 100.0, 1), 6,
                   fillColor=bar_color, strokeColor=None, rx=3, ry=3))
    return d


def th(txt, align=TA_LEFT):
    return Paragraph(f"<b>{txt}</b>", ps(f"TH_{txt[:8]}",
        fontName="Helvetica-Bold", fontSize=7.5, textColor=C_WHITE,
        letterSpacing=0.3, leading=10, alignment=align))


def td(txt, bold=False, color=C_SLATE8, size=8.5, align=TA_LEFT):
    return Paragraph(str(txt), ps(f"TD_{str(txt)[:8]}",
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
        [Paragraph(f"<b>{title.upper()}</b>", ps(f"SH_{title[:8]}",
            fontName="Helvetica-Bold", fontSize=11, textColor=C_SLATE8, leading=14))],
        [Paragraph(subtitle, ps(f"SS_{title[:8]}",
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


def _risk_pill_key(nivel):
    return {"bajo": "green", "medio": "amber", "alto": "red", "critico": "red"}.get(nivel, "slate")


def _severity_pill_key(sev):
    return {"info": "blue", "warning": "amber", "critical": "red", "ok": "green"}.get(sev, "slate")


_SEVERITY_LABELS = {"info": "INFO", "warning": "ADVERT.", "critical": "CRÍTICO", "ok": "OK"}
_PRIORITY_LABELS = {"baja": "BAJA", "media": "MEDIA", "alta": "ALTA", "critica": "CRÍTICA"}


# ── Función principal ────────────────────────────────────────────────────────
def build_security_report_pdf(client) -> bytes:
    from django.conf import settings
    from core.models import SecurityCheck, SecurityAnomalyEvent, SignInAnomalyEvent

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    now = timezone.localtime(timezone.now())

    latest = SecurityCheck.objects.filter(client=client).order_by("-checked_at").first()
    domains = list(client.domains.all())
    anomalies = list(SecurityAnomalyEvent.objects.filter(
        device__client=client
    ).select_related("device").order_by("-detected_at")[:50])
    signin_anomalies = list(SignInAnomalyEvent.objects.filter(
        client=client
    ).order_by("-detected_at")[:50])

    ai = latest.ai_summary if (latest and latest.ai_summary) else None

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
            f'<font color="#93c5fd" size="9">Reporte de Postura de Seguridad</font><br/>'
            f'<font color="white" size="18"><b>{now.strftime("%d/%m/%Y")}</b></font>',
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
            [Paragraph(str(value), ps(f"iv_{str(value)[:4]}",
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=size, textColor=C_SLATE8, leading=size + 4))],
        ], colWidths=[None])

    riesgo_txt = ai.get("nivel_riesgo", "—").upper() if ai else "SIN ANÁLISIS"
    cli = Table([[
        info_cell("CLIENTE",       client.company_name, size=13),
        info_cell("CONTACTO",      client.contact_email, size=9, bold=False),
        info_cell("NIVEL DE RIESGO", riesgo_txt, size=11),
        info_cell("GENERADO",      now.strftime("%d/%m/%Y %H:%M"), size=9, bold=False),
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

    # ── RESUMEN EJECUTIVO IA ─────────────────────────────────────────────────
    story += section_header("Resumen Ejecutivo",
                             "Análisis general de la postura de seguridad")
    if ai:
        resumen_box = Table([[
            Paragraph(ai.get("resumen", ""), ps("resumen", fontSize=10, textColor=C_SLATE8, leading=15)),
            pill_cell(f"RIESGO {riesgo_txt}", _risk_pill_key(ai.get("nivel_riesgo"))),
        ]], colWidths=[CW*0.75, CW*0.25])
        resumen_box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#eff6ff")),
            ("LEFTPADDING",   (0,0), (-1,-1), 14),
            ("RIGHTPADDING",  (0,0), (-1,-1), 14),
            ("TOPPADDING",    (0,0), (-1,-1), 12),
            ("BOTTOMPADDING", (0,0), (-1,-1), 12),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            ("ALIGN",         (1,0), (1,0),   "RIGHT"),
            ("LINEBELOW",     (0,0), (-1,-1), 2, C_BLUE),
        ]))
    else:
        resumen_box = Table([[
            Paragraph("No se ha generado un análisis de seguridad con IA para este cliente todavía.",
                      ps("resumen", fontSize=10, textColor=C_SLATE5, leading=15)),
        ]], colWidths=[CW])
        resumen_box.setStyle(TableStyle([
            ("BACKGROUND",    (0,0), (-1,-1), C_SLATE0),
            ("LEFTPADDING",   (0,0), (-1,-1), 14),
            ("RIGHTPADDING",  (0,0), (-1,-1), 14),
            ("TOPPADDING",    (0,0), (-1,-1), 12),
            ("BOTTOMPADDING", (0,0), (-1,-1), 12),
        ]))
    story.append(resumen_box)
    story.append(Spacer(1, 18))

    # ── INDICADORES: Secure Score y MFA ─────────────────────────────────────
    story += section_header("Indicadores M365",
                             "Microsoft Secure Score y cobertura de autenticación multifactor")

    if latest:
        ss_pct  = latest.secure_score_percent
        mfa_pct = latest.mfa_percent

        def indicator_row(label, value_txt, pct, color):
            bar = progress_bar(pct or 0, color, width=140)
            return [
                td(label, bold=True, size=9.5),
                td(value_txt, size=9.5, align=TA_RIGHT),
                bar,
                pill_cell(f"{pct:.0f}%" if pct is not None else "—",
                          "green" if (pct or 0) >= 70 else ("amber" if (pct or 0) >= 40 else "red")),
            ]

        rows = [[th("INDICADOR"), th("VALOR", TA_RIGHT), th("PROGRESO", TA_CENTER), th("", TA_CENTER)]]

        if latest.secure_score is not None:
            rows.append(indicator_row(
                "Microsoft Secure Score",
                f"{latest.secure_score:.0f} / {latest.secure_score_max:.0f}",
                ss_pct,
                C_GREEN if (ss_pct or 0) >= 70 else (C_AMBER if (ss_pct or 0) >= 40 else C_RED),
            ))
        else:
            rows.append([td("Microsoft Secure Score", bold=True, size=9.5),
                         td("Sin datos disponibles", size=9, color=C_SLATE5), "", ""])

        if latest.mfa_total is not None:
            rows.append(indicator_row(
                "Cobertura MFA",
                f"{latest.mfa_registered} / {latest.mfa_total} usuarios",
                mfa_pct,
                C_GREEN if (mfa_pct or 0) >= 90 else (C_AMBER if (mfa_pct or 0) >= 50 else C_RED),
            ))
        else:
            rows.append([td("Cobertura MFA", bold=True, size=9.5),
                         td("Sin datos disponibles", size=9, color=C_SLATE5), "", ""])

        ind_table = Table(rows, colWidths=[CW*0.32, CW*0.28, CW*0.25, CW*0.15])
        ind_table.setStyle(TableStyle(TH_STYLE + [
            ("ALIGN", (2,1), (2,-1), "CENTER"),
            ("ALIGN", (3,1), (3,-1), "CENTER"),
        ]))
        story.append(ind_table)

        # Usuarios sin MFA
        no_mfa = (latest.check_details or {}).get("mfa", {}).get("no_mfa_users") or []
        if no_mfa:
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                f"<b>Usuarios sin MFA registrado:</b> " + ", ".join(no_mfa[:10]) +
                (f" y {len(no_mfa)-10} más..." if len(no_mfa) > 10 else ""),
                ps("nomfa", fontSize=8.5, textColor=C_SLATE5, leading=12)))

        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"Última verificación: {timezone.localtime(latest.checked_at).strftime('%d/%m/%Y %H:%M')}",
            ps("lastcheck", fontSize=7.5, textColor=C_SLATE5)))
    else:
        story.append(Paragraph(
            "No se ha ejecutado ninguna verificación de seguridad M365 para este cliente.",
            ps("nodata", fontSize=9, textColor=C_SLATE5)))

    story.append(Spacer(1, 18))

    # ── CERTIFICADOS SSL ─────────────────────────────────────────────────────
    story += section_header("Certificados SSL",
                             "Estado de los certificados de dominios monitoreados")
    if domains:
        rows = [[th("DOMINIO"), th("ESTADO"), th("VENCE"), th("DÍAS"), th("EMISOR")]]
        for d in domains:
            if d.ssl_error:
                estado_pill = pill_cell("ERROR", "red")
                vence_txt, dias_txt = "—", "—"
            elif d.ssl_status == "ok":
                estado_pill = pill_cell("OK", "green")
                vence_txt = d.ssl_expiry_date.strftime("%d/%m/%Y") if d.ssl_expiry_date else "—"
                dias_txt = str(d.days_until_ssl_expiry) if d.days_until_ssl_expiry is not None else "—"
            elif d.ssl_status in ("warning", "critical", "expired"):
                key = "red" if d.ssl_status in ("critical", "expired") else "amber"
                estado_pill = pill_cell(d.get_ssl_status_display().upper(), key)
                vence_txt = d.ssl_expiry_date.strftime("%d/%m/%Y") if d.ssl_expiry_date else "—"
                dias_txt = str(d.days_until_ssl_expiry) if d.days_until_ssl_expiry is not None else "—"
            else:
                estado_pill = pill_cell("DESCONOCIDO", "slate")
                vence_txt, dias_txt = "—", "—"

            rows.append([
                td(d.fqdn, bold=True),
                estado_pill,
                td(vence_txt, align=TA_CENTER),
                td(dias_txt, align=TA_CENTER),
                td(d.ssl_issuer or (d.ssl_error[:40] if d.ssl_error else "—"), size=8, color=C_SLATE5),
            ])

        dom_table = Table(rows, colWidths=[CW*0.28, CW*0.16, CW*0.16, CW*0.10, CW*0.30])
        dom_table.setStyle(TableStyle(TH_STYLE + [
            ("ALIGN", (1,0), (1,-1), "CENTER"),
            ("ALIGN", (2,0), (3,-1), "CENTER"),
        ]))
        story.append(dom_table)
    else:
        story.append(Paragraph("Este cliente no tiene dominios configurados.",
                                ps("nodom", fontSize=9, textColor=C_SLATE5)))

    story.append(Spacer(1, 18))

    # ── HALLAZGOS Y RECOMENDACIONES IA ──────────────────────────────────────
    if ai and (ai.get("hallazgos") or ai.get("recomendaciones")):
        story += section_header("Hallazgos del Análisis IA",
                                 "Observaciones detectadas en la última evaluación")
        if ai.get("hallazgos"):
            rows = [[th("HALLAZGO"), th("DESCRIPCIÓN"), th("SEVERIDAD")]]
            for h in ai["hallazgos"]:
                rows.append([
                    td(h.get("titulo",""), bold=True),
                    td(h.get("detalle",""), size=8, color=C_SLATE5),
                    pill_cell(_SEVERITY_LABELS.get(h.get("severidad"), "INFO"), _severity_pill_key(h.get("severidad"))),
                ])
            t = Table(rows, colWidths=[CW*0.28, CW*0.55, CW*0.17])
            t.setStyle(TableStyle(TH_STYLE + [("ALIGN", (2,0), (2,-1), "CENTER")]))
            story.append(t)
            story.append(Spacer(1, 14))

        if ai.get("recomendaciones"):
            story.append(Paragraph("RECOMENDACIONES", ps("rec_h",
                fontName="Helvetica-Bold", fontSize=10, textColor=C_SLATE8, leading=14)))
            story.append(Spacer(1, 6))
            rows = [[th("ACCIÓN"), th("IMPACTO"), th("PRIORIDAD")]]
            for r in ai["recomendaciones"]:
                rows.append([
                    td(r.get("accion",""), bold=True, size=8.5),
                    td(r.get("impacto",""), size=8, color=C_SLATE5),
                    pill_cell(_PRIORITY_LABELS.get(r.get("prioridad"), "MEDIA"),
                              "red" if r.get("prioridad") in ("alta","critica") else
                              ("amber" if r.get("prioridad")=="media" else "slate")),
                ])
            t = Table(rows, colWidths=[CW*0.42, CW*0.41, CW*0.17])
            t.setStyle(TableStyle(TH_STYLE + [("ALIGN", (2,0), (2,-1), "CENTER")]))
            story.append(t)

        story.append(Spacer(1, 18))

    # ── ANOMALÍAS DE SEGURIDAD (AGENTE) ──────────────────────────────────────
    story.append(PageBreak())
    story += section_header("Anomalías de Seguridad Detectadas",
                             "Cambios identificados por el agente (administradores, inicio, tareas programadas)")
    if anomalies:
        rows = [[th("FECHA"), th("EQUIPO"), th("TIPO"), th("DETALLE"), th("ESTADO")]]
        for a in anomalies:
            sev_key = _severity_pill_key(a.severity)
            estado_pill = pill_cell("REVISADA", "green") if a.status == "acknowledged" \
                else pill_cell(_SEVERITY_LABELS.get(a.severity, "INFO"), sev_key)
            rows.append([
                td(timezone.localtime(a.detected_at).strftime("%d/%m/%Y %H:%M"), size=8),
                td(a.device.display_name, size=8.5),
                td(a.get_anomaly_type_display(), size=8),
                td(a.detail_summary, size=8, color=C_SLATE5),
                estado_pill,
            ])
        t = Table(rows, colWidths=[CW*0.15, CW*0.15, CW*0.17, CW*0.33, CW*0.20], repeatRows=1)
        t.setStyle(TableStyle(TH_STYLE + [("ALIGN", (4,0), (4,-1), "CENTER")]))
        story.append(t)

        open_count = sum(1 for a in anomalies if a.status == "open")
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"<b>{open_count}</b> anomalía(s) sin revisar de un total de <b>{len(anomalies)}</b> registradas "
            f"(últimas 50).",
            ps("anom_summary", fontSize=8.5, textColor=C_SLATE5)))
    else:
        story.append(Paragraph(
            "No se han detectado anomalías de seguridad en los dispositivos de este cliente.",
            ps("noanom", fontSize=9, textColor=C_SLATE5)))

    # ── INICIOS DE SESIÓN SOSPECHOSOS (M365) ─────────────────────────────────
    if signin_anomalies:
        story.append(Spacer(1, 18))
        story += section_header("Inicios de Sesión Sospechosos (M365)",
                                 "Países nuevos, viaje imposible y sign-ins riesgosos detectados")
        rows = [[th("FECHA"), th("TIPO"), th("DETALLE"), th("ESTADO")]]
        for a in signin_anomalies:
            sev_key = _severity_pill_key(a.severity)
            estado_pill = pill_cell("REVISADA", "green") if a.status == "acknowledged" \
                else pill_cell(_SEVERITY_LABELS.get(a.severity, "INFO"), sev_key)
            rows.append([
                td(timezone.localtime(a.detected_at).strftime("%d/%m/%Y %H:%M"), size=8),
                td(a.get_anomaly_type_display(), size=8),
                td(a.detail_summary, size=8, color=C_SLATE5),
                estado_pill,
            ])
        t = Table(rows, colWidths=[CW*0.15, CW*0.20, CW*0.45, CW*0.20], repeatRows=1)
        t.setStyle(TableStyle(TH_STYLE + [("ALIGN", (3,0), (3,-1), "CENTER")]))
        story.append(t)

        open_count = sum(1 for a in signin_anomalies if a.status == "open")
        story.append(Spacer(1, 8))
        story.append(Paragraph(
            f"<b>{open_count}</b> anomalía(s) sin revisar de un total de <b>{len(signin_anomalies)}</b> "
            f"registradas (últimas 50).",
            ps("signin_summary", fontSize=8.5, textColor=C_SLATE5)))

    # ── Build ────────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=footer_cb, onLaterPages=footer_cb)
    return buf.getvalue()
