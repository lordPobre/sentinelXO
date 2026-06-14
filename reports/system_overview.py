"""
Sentinel XO — Documento de Producto
Funcionamiento, arquitectura, módulos y beneficios de la plataforma.
ReportLab puro, mismo estilo visual que security_report.py / generator.py.
"""
import io
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, PageBreak)
from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

from reports.security_report import (
    ps, th, td, pill_cell, section_header, footer_cb,
    C_DARK, C_BLUE, C_SLATE8, C_SLATE5, C_SLATE3, C_SLATE1, C_SLATE0, C_WHITE,
    C_GREEN, C_AMBER, C_RED,
    PAGE_W, PAGE_H, ML, MR, MT, MB, CW,
)

C_PURPLE = colors.HexColor("#7c3aed")


# ── Helpers específicos de este documento ──────────────────────────────────

def stat_box(value, label):
    inner = Table([
        [Paragraph(value, ps("stv", fontName="Helvetica-Bold", fontSize=20,
                              textColor=C_BLUE, leading=24, alignment=TA_CENTER))],
        [Paragraph(label, ps("stl", fontSize=8, textColor=C_SLATE5,
                              leading=11, alignment=TA_CENTER))],
    ], colWidths=[None])
    inner.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_SLATE0),
        ("TOPPADDING",    (0,0), (0,0), 12),
        ("BOTTOMPADDING", (0,0), (0,0), 2),
        ("TOPPADDING",    (0,1), (0,1), 0),
        ("BOTTOMPADDING", (0,1), (0,1), 12),
        ("LINEBELOW",     (0,0), (-1,-1), 2, C_BLUE),
    ]))
    return inner


def arch_box(title, subtitle, items, accent):
    rows = [
        [Paragraph(f'<font color="white"><b>{title}</b></font><br/>'
                   f'<font color="#cbd5e1" size="7">{subtitle}</font>',
                   ps("ab_h", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_WHITE, leading=13, alignment=TA_CENTER))],
    ]
    for it in items:
        rows.append([Paragraph(f"•  {it}", ps("ab_i", fontSize=7.5,
                                                textColor=C_SLATE8, leading=11.5))])
    t = Table(rows, colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (0,0),  C_DARK),
        ("TOPPADDING",    (0,0), (0,0),  10),
        ("BOTTOMPADDING", (0,0), (0,0),  10),
        ("BACKGROUND",    (0,1), (-1,-1), C_SLATE0),
        ("TOPPADDING",    (0,1), (-1,-1), 5),
        ("BOTTOMPADDING", (0,1), (-1,-1), 5),
        ("LEFTPADDING",   (0,0), (-1,-1), 9),
        ("RIGHTPADDING",  (0,0), (-1,-1), 9),
        ("BOX",           (0,0), (-1,-1), 1.2, accent),
        ("LINEBELOW",     (0,-1), (-1,-1), 1.2, accent),
    ]))
    return t


def arch_arrow():
    return Paragraph("→", ps("arr", fontName="Helvetica-Bold", fontSize=16,
                              textColor=C_SLATE3, leading=16, alignment=TA_CENTER))


def module_card(title, desc, accent=C_BLUE):
    inner = Table([
        [Paragraph(f"<b>{title}</b>", ps("mc_t", fontSize=9.5,
                                          textColor=C_SLATE8, leading=13))],
        [Paragraph(desc, ps("mc_d", fontSize=8, textColor=C_SLATE5, leading=11.5))],
    ], colWidths=[None])
    inner.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), C_SLATE0),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("TOPPADDING",    (0,0), (0,0), 8),
        ("BOTTOMPADDING", (0,0), (0,0), 3),
        ("TOPPADDING",    (0,1), (0,1), 0),
        ("BOTTOMPADDING", (0,1), (0,1), 9),
        ("LINEBEFORE",    (0,0), (0,-1), 2.2, accent),
    ]))
    return inner


def module_grid(cards):
    """Recibe una lista de Tables (module_card) y las dispone en 2 columnas."""
    rows = []
    for i in range(0, len(cards), 2):
        left = cards[i]
        right = cards[i+1] if i+1 < len(cards) else Spacer(1, 1)
        rows.append([left, right])
    t = Table(rows, colWidths=[CW*0.49, CW*0.49], rowHeights=None)
    t.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("TOPPADDING",   (0,0), (-1,-1), 0),
        ("BOTTOMPADDING",(0,0), (-1,-1), 8),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ]))
    return t


def benefit_column(title, accent, items):
    rows = [
        [Paragraph(f'<font color="white"><b>{title}</b></font>',
                   ps("bc_h", fontName="Helvetica-Bold", fontSize=10,
                      textColor=C_WHITE, leading=14))],
    ]
    for it in items:
        rows.append([Paragraph(f"✓&nbsp;&nbsp;{it}", ps("bc_i", fontSize=8.5,
                                                          textColor=C_SLATE8, leading=13))])
    t = Table(rows, colWidths=[None])
    style = [
        ("BACKGROUND",    (0,0), (0,0),  accent),
        ("TOPPADDING",    (0,0), (0,0),  9),
        ("BOTTOMPADDING", (0,0), (0,0),  9),
        ("BACKGROUND",    (0,1), (-1,-1), C_SLATE0),
        ("LEFTPADDING",   (0,0), (-1,-1), 12),
        ("RIGHTPADDING",  (0,0), (-1,-1), 12),
        ("TOPPADDING",    (0,1), (-1,-1), 7),
        ("BOTTOMPADDING", (0,1), (-1,-1), 7),
        ("LINEBELOW",     (0,1), (-1,-2), 0.5, C_SLATE3),
    ]
    t.setStyle(TableStyle(style))
    return t


# ── Función principal ─────────────────────────────────────────────────────

def build_system_overview_pdf() -> bytes:
    from django.conf import settings

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    now = timezone.localtime(timezone.now())

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB)
    story = []

    # ── HEADER FULL-BLEED ────────────────────────────────────────────────────
    hdr = Table([[
        Paragraph(
            f'<font color="white" size="18"><b>{company}</b></font><br/>'
            f'<font color="#cbd5e1" size="9">Plataforma de Monitoreo y Seguridad MSP</font>',
            ps("hL", fontName="Helvetica-Bold", fontSize=18,
               textColor=C_WHITE, leading=22)),
        Paragraph(
            f'<font color="#93c5fd" size="9">Documento de Producto</font><br/>'
            f'<font color="white" size="14"><b>Funcionamiento y Arquitectura</b></font>',
            ps("hR", fontSize=9, textColor=colors.HexColor("#93c5fd"),
               leading=20, alignment=TA_RIGHT)),
    ]], colWidths=[CW * 0.58, CW * 0.42])
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
    story.append(Spacer(1, 14))

    # ── INTRODUCCIÓN ─────────────────────────────────────────────────────────
    story.append(Paragraph(
        f"<b>{company}</b> es una plataforma SaaS de monitoreo y seguridad gestionada (MSP) "
        f"que centraliza la supervisión de equipos, infraestructura M365, dominios y "
        f"certificados de todos los clientes en un único panel. Un agente liviano instalado "
        f"en cada equipo Windows envía telemetría y huellas de seguridad de forma cifrada y "
        f"firmada al servidor, donde son procesadas, almacenadas y analizadas — incluyendo "
        f"análisis asistido por inteligencia artificial — para generar reportes, alertas y "
        f"recomendaciones accionables.",
        ps("intro", fontSize=9.5, textColor=C_SLATE8, leading=15)))
    story.append(Spacer(1, 14))

    # Stats destacados
    stats = Table([[
        stat_box("16", "Módulos integrados"),
        stat_box("60s", "Intervalo de telemetría"),
        stat_box("IA", "Análisis y diagnóstico"),
        stat_box("24/7", "Monitoreo continuo"),
    ]], colWidths=[CW*0.25]*4)
    stats.setStyle(TableStyle([
        ("LEFTPADDING", (0,0), (-1,-1), 4), ("RIGHTPADDING", (0,0), (-1,-1), 4),
        ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(stats)
    story.append(Spacer(1, 18))

    # ── ARQUITECTURA ─────────────────────────────────────────────────────────
    story += section_header("Arquitectura del Sistema",
                             "Tres capas — agentes en el cliente, backend en la nube y portal web")

    arch = Table([[
        arch_box("AGENTES CLIENTE", "Windows · Python",
                 ["CPU, RAM, disco, red y GPU",
                  "Huella de seguridad y software",
                  "Firma HMAC-SHA256 por solicitud",
                  "Envío periódico vía HTTPS"],
                 colors.HexColor("#64748b")),
        arch_arrow(),
        arch_box("BACKEND", "Django · PostgreSQL · Celery",
                 ["Almacenamiento y procesamiento",
                  "Tareas programadas (Celery + Redis)",
                  "Análisis con IA (Claude, Anthropic)",
                  "Generación de reportes PDF"],
                 C_BLUE),
        arch_arrow(),
        arch_box("PORTAL WEB", "HTMX · Tailwind",
                 ["Monitoreo en tiempo real",
                  "Panel de seguridad y reportes",
                  "Portal dedicado por cliente",
                  "Alertas: email y Telegram"],
                 C_GREEN),
    ]], colWidths=[CW*0.30, CW*0.06, CW*0.30, CW*0.06, CW*0.28])
    arch.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 2), ("RIGHTPADDING", (0,0), (-1,-1), 2),
        ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 0),
    ]))
    story.append(arch)
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "Cada agente envía su información firmada digitalmente; el backend valida la firma, "
        "almacena los datos, ejecuta tareas periódicas (verificación de dominios, anomalías de "
        "seguridad, respaldos) y genera análisis con IA. El portal web consulta esta información "
        "para mostrar el estado en tiempo real, generar reportes y enviar alertas por email y Telegram.",
        ps("archtxt", fontSize=8.5, textColor=C_SLATE5, leading=13)))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "<b>Stack tecnológico:</b> Django 5 · PostgreSQL · Celery/Redis · HTMX + Tailwind · "
        "ReportLab (PDF) · Railway (hosting) · Claude API (Anthropic)",
        ps("stack", fontSize=8, textColor=C_SLATE5, leading=12)))

    # ── MÓDULOS: MONITOREO DE INFRAESTRUCTURA ────────────────────────────────
    story.append(PageBreak())
    story += section_header("Monitoreo de Infraestructura",
                             "Visibilidad continua del estado de cada equipo")
    story.append(module_grid([
        module_card("Telemetría en Tiempo Real",
                     "CPU, RAM, disco, red, temperatura y GPU (NVIDIA/AMD/Intel) capturados "
                     "cada 60 segundos, con historial y gráficos de tendencia.", C_BLUE),
        module_card("Monitor de Flota en Vivo",
                     "Vista consolidada de todos los equipos de un cliente, con actualización "
                     "automática cada 5 segundos y alertas visuales por umbral.", C_BLUE),
        module_card("Alertas de Conectividad",
                     "Si un equipo deja de reportar, se crea un incidente automático con "
                     "diagnóstico por IA y notificación; al reconectar, se avisa la duración "
                     "de la caída.", C_AMBER),
        module_card("Reportes Automatizados (PDF)",
                     "Reportes diarios, semanales y mensuales por equipo o cliente, con "
                     "resumen narrativo generado por IA, listos para compartir.", C_BLUE),
    ]))
    story.append(Spacer(1, 14))

    # ── MÓDULOS: SEGURIDAD INTEGRAL ───────────────────────────────────────────
    story += section_header("Seguridad Integral",
                             "Postura de seguridad de equipos, M365, dominios y software")
    story.append(module_grid([
        module_card("Postura Microsoft 365",
                     "Secure Score, cobertura de MFA por usuario y estado general de "
                     "seguridad del tenant, con análisis y recomendaciones por IA.", C_RED),
        module_card("Certificados SSL y Dominios",
                     "Verificación de vencimiento de dominios (WHOIS) y certificados "
                     "SSL, con alertas anticipadas por email y Telegram (7 días o menos).", C_RED),
        module_card("Detección de Anomalías del Sistema",
                     "El agente detecta cambios en administradores locales, programas de "
                     "inicio y tareas programadas, generando alertas según severidad.", C_RED),
        module_card("Monitoreo de Inicios de Sesión",
                     "Analiza los accesos a Microsoft 365 y detecta países nuevos, viajes "
                     "imposibles y accesos de alto riesgo.", C_RED),
        module_card("Inventario de Software y CVE",
                     "Catálogo completo del software instalado por equipo, con detección de "
                     "cambios y análisis de vulnerabilidades (CVE) asistido por IA.", C_RED),
        module_card("2FA y Registro de Auditoría",
                     "Autenticación de dos factores (TOTP) para el acceso al panel, y "
                     "registro de auditoría de inicios de sesión y accesos.", C_RED),
    ]))
    story.append(Spacer(1, 14))

    # ── MÓDULOS: NOTIFICACIONES Y CONTINUIDAD ────────────────────────────────
    story += section_header("Notificaciones y Continuidad",
                             "Comunicación inmediata y respaldo de la información")
    story.append(module_grid([
        module_card("Alertas Multi-canal",
                     "Notificaciones por email para todos los eventos, y por Telegram para "
                     "los eventos críticos (equipos offline, anomalías graves, vencimientos).", C_GREEN),
        module_card("Respaldo Automático",
                     "Copia de seguridad semanal de la base de datos, comprimida y enviada "
                     "automáticamente por correo al equipo técnico.", C_GREEN),
        module_card("Comunicación Segura (HMAC)",
                     "Cada envío del agente al servidor está firmado digitalmente "
                     "(HMAC-SHA256), evitando suplantación de telemetría.", C_GREEN),
        module_card("Encabezados de Seguridad Web",
                     "Política de seguridad de contenido (CSP) y cabeceras HTTP "
                     "endurecidas en todo el portal.", C_GREEN),
    ]))
    story.append(Spacer(1, 14))

    # ── MÓDULOS: GESTIÓN Y COLABORACIÓN ──────────────────────────────────────
    story += section_header("Gestión y Colaboración",
                             "Herramientas para el equipo técnico y para el cliente final")
    story.append(module_grid([
        module_card("Gestión de Incidentes con IA",
                     "Registro de incidentes con diagnóstico asistido por IA, seguimiento "
                     "de estado y trazabilidad completa para auditoría.", C_PURPLE),
        module_card("Portal Dedicado por Cliente",
                     "Cada cliente accede a su propio panel con disponibilidad mensual, "
                     "equipos, dominios, licencias M365 e incidentes recientes.", C_PURPLE),
        module_card("Monitoreo de Email / M365",
                     "Supervisión de licencias, entregabilidad y estado general del entorno "
                     "de correo corporativo del cliente.", C_PURPLE),
    ]))

    # ── BENEFICIOS ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 14))
    story += section_header("Beneficios",
                             "Valor para el equipo técnico y para los clientes finales")

    benefits = Table([[
        benefit_column("Para el equipo técnico (MSP)", C_DARK, [
            "Visibilidad centralizada de todos los clientes en un solo panel.",
            "Detección proactiva de problemas antes de que el cliente los reporte.",
            "Automatización de reportes — menos trabajo manual y más consistencia.",
            "Diferenciación: ofrecer seguridad gestionada como servicio premium.",
            "Escalable: incorporar nuevos clientes y equipos sin fricción.",
            "Alertas críticas inmediatas vía Telegram, sin depender solo del email.",
        ]),
        benefit_column("Para los clientes finales", C_BLUE, [
            "Transparencia total: portal propio con su estado en tiempo real.",
            "Reportes profesionales en PDF, listos para presentar a directorio.",
            "Menos incidentes gracias a la detección y corrección temprana.",
            "Cumplimiento y trazabilidad: auditoría de accesos y cambios.",
            "Continuidad asegurada con respaldo automático de información.",
            "Comunicación inmediata ante eventos críticos de seguridad.",
        ]),
    ]], colWidths=[CW*0.49, None])
    benefits.setStyle(TableStyle([
        ("LEFTPADDING", (0,0), (-1,-1), 0), ("RIGHTPADDING", (1,0), (1,0), 0),
        ("RIGHTPADDING", (0,0), (0,0), 10),
        ("TOPPADDING", (0,0), (-1,-1), 0), ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ]))
    story.append(benefits)
    story.append(Spacer(1, 16))

    story.append(Paragraph(
        f"<b>{company}</b> reúne en una sola plataforma lo que normalmente requeriría varias "
        f"herramientas independientes — monitoreo de infraestructura, seguridad gestionada, "
        f"gestión de incidentes y reportería — con análisis asistido por IA en cada módulo "
        f"clave, entregando una postura de seguridad y disponibilidad medible y "
        f"comunicable a cada cliente.",
        ps("closing", fontSize=9, textColor=C_SLATE8, leading=14)))

    # ── Build ────────────────────────────────────────────────────────────────
    doc.build(story, onFirstPage=footer_cb, onLaterPages=footer_cb)
    return buf.getvalue()
