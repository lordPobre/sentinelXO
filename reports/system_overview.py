"""
Sentinel XO — Documento de Producto (Funcionamiento y Arquitectura)
===================================================================
Reconstruido sobre `reports.pdf_theme`. Sin datos de cliente: documento
estático de marketing/producto. `build_system_overview_pdf()` no recibe args.
"""
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import SimpleDocTemplate, Spacer, PageBreak, Table, TableStyle
from reportlab.graphics.shapes import Drawing, Rect

from reports import pdf_theme as T

C_PURPLE = T.PURPLE


# ── Componentes locales (construidos sobre el theme) ─────────────────────────
def stat_box(value, label, accent=T.BRAND):
    inner = Table([
        [T.P(value, fontName=T.MONO_SB, fontSize=19, textColor=accent, leading=22, alignment=TA_CENTER)],
        [T.P(label, fontName=T.FONT, fontSize=7.6, textColor=T.MUTED, leading=10.5, alignment=TA_CENTER)],
    ], colWidths=[None])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), T.SUBTLE),
        ("BOX", (0, 0), (-1, -1), 0.75, T.LINE),
        ("LINEABOVE", (0, 0), (-1, 0), 2.4, accent),
        ("TOPPADDING", (0, 0), (0, 0), 12), ("BOTTOMPADDING", (0, 0), (0, 0), 3),
        ("TOPPADDING", (0, 1), (0, 1), 0), ("BOTTOMPADDING", (0, 1), (0, 1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return inner


def arch_box(title, subtitle, items, accent):
    rows = [[T.P(f'<font color="white"><b>{title}</b></font><br/>'
                 f'<font color="#9DB2D6" size="7">{subtitle}</font>',
                 fontName=T.FONT_SB, fontSize=10, textColor=T.PAPER, leading=13, alignment=TA_CENTER)]]
    for it in items:
        rows.append([T.P(f"•  {it}", fontName=T.FONT, fontSize=7.5, textColor=T.BODY, leading=11.5)])
    t = Table(rows, colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), T.INK),
        ("TOPPADDING", (0, 0), (0, 0), 10), ("BOTTOMPADDING", (0, 0), (0, 0), 10),
        ("BACKGROUND", (0, 1), (-1, -1), T.SUBTLE),
        ("TOPPADDING", (0, 1), (-1, -1), 5), ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("BOX", (0, 0), (-1, -1), 1, T.LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 2, accent),
    ]))
    return t


def arch_arrow():
    return T.P("→", fontName=T.FONT_SB, fontSize=15, textColor=T.FAINT, leading=15, alignment=TA_CENTER)


def module_card(title, desc, accent=T.BRAND):
    inner = Table([
        [T.P(f"<b>{title}</b>", fontName=T.FONT_SB, fontSize=9.5, textColor=T.TEXT, leading=13)],
        [T.P(desc, fontName=T.FONT, fontSize=8, textColor=T.MUTED, leading=11.5)],
    ], colWidths=[None])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), T.SUBTLE),
        ("LEFTPADDING", (0, 0), (-1, -1), 11), ("RIGHTPADDING", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (0, 0), 9), ("BOTTOMPADDING", (0, 0), (0, 0), 3),
        ("TOPPADDING", (0, 1), (0, 1), 0), ("BOTTOMPADDING", (0, 1), (0, 1), 10),
        ("LINEBEFORE", (0, 0), (0, -1), 2.4, accent),
    ]))
    return inner


def module_grid(cards):
    rows = []
    for i in range(0, len(cards), 2):
        left = cards[i]
        right = cards[i + 1] if i + 1 < len(cards) else Spacer(1, 1)
        rows.append([left, right])
    t = Table(rows, colWidths=[T.CW * 0.485, T.CW * 0.485])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (0, 0), (0, -1), 8),
        ("LEFTPADDING", (1, 0), (1, -1), 8), ("RIGHTPADDING", (1, 0), (1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def benefit_column(title, accent, items):
    chex = "#" + accent.hexval()[2:]
    rows = [[T.P(f'<font color="white"><b>{title}</b></font>',
                 fontName=T.FONT_SB, fontSize=10, textColor=T.PAPER, leading=14)]]
    for it in items:
        rows.append([T.P(f'<font color="{chex}"><b>&#10003;</b></font>&nbsp;&nbsp;{it}',
                         fontName=T.FONT, fontSize=8.5, textColor=T.BODY, leading=13)])
    t = Table(rows, colWidths=[None])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), accent),
        ("TOPPADDING", (0, 0), (0, 0), 9), ("BOTTOMPADDING", (0, 0), (0, 0), 9),
        ("BACKGROUND", (0, 1), (-1, -1), T.SUBTLE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 1), (-1, -1), 7), ("BOTTOMPADDING", (0, 1), (-1, -1), 7),
        ("LINEBELOW", (0, 1), (-1, -2), 0.5, T.LINE),
    ]))
    return t


# ════════════════════════════════════════════════════════════════════════════
def build_system_overview_pdf() -> bytes:
    from django.conf import settings
    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")
    return _render(company, support)


def _render(company, support) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=T.ML, rightMargin=T.MR,
                            topMargin=T.MT, bottomMargin=T.MB)
    story = []

    story += T.header_band(company, "Documento de Producto", "Funcionamiento y Arquitectura")

    story.append(T.P(
        f"<b>{company}</b> es una plataforma SaaS de monitoreo y seguridad gestionada (MSP) "
        f"que centraliza la supervisión de equipos, infraestructura M365, dominios y "
        f"certificados de todos los clientes en un único panel. Un agente liviano instalado "
        f"en cada equipo Windows envía telemetría y huellas de seguridad de forma cifrada y "
        f"firmada al servidor, donde son procesadas, almacenadas y analizadas — incluyendo "
        f"análisis asistido por inteligencia artificial — para generar reportes, alertas y "
        f"recomendaciones accionables.",
        fontName=T.FONT, fontSize=9.5, textColor=T.BODY, leading=15))
    story.append(T.gap(14))

    stats = Table([[
        stat_box("16", "Módulos integrados"),
        stat_box("60s", "Intervalo de telemetría", T.CYAN),
        stat_box("IA", "Análisis y diagnóstico", T.PURPLE),
        stat_box("24/7", "Monitoreo continuo", T.GREEN),
    ]], colWidths=[T.CW * 0.25] * 4)
    stats.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (3, 0), (3, 0), 0),
        ("LEFTPADDING", (1, 0), (3, 0), 5), ("RIGHTPADDING", (0, 0), (2, 0), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(stats)
    story.append(T.gap(18))

    # Arquitectura
    story += T.section("Arquitectura del Sistema",
                       "Tres capas — agentes en el cliente, backend en la nube y portal web")
    arch = Table([[
        arch_box("AGENTES CLIENTE", "Windows · Python",
                 ["CPU, RAM, disco, red y GPU", "Huella de seguridad y software",
                  "Firma HMAC-SHA256 por solicitud", "Envío periódico vía HTTPS"], T.MUTED),
        arch_arrow(),
        arch_box("BACKEND", "Django · PostgreSQL · Celery",
                 ["Almacenamiento y procesamiento", "Tareas programadas (Celery + Redis)",
                  "Análisis con IA (Claude, Anthropic)", "Generación de reportes PDF"], T.BRAND),
        arch_arrow(),
        arch_box("PORTAL WEB", "HTMX · Tailwind",
                 ["Monitoreo en tiempo real", "Panel de seguridad y reportes",
                  "Portal dedicado por cliente", "Alertas: email y Telegram"], T.GREEN),
    ]], colWidths=[T.CW * 0.30, T.CW * 0.06, T.CW * 0.30, T.CW * 0.06, T.CW * 0.28])
    arch.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(arch)
    story.append(T.gap(8))
    story.append(T.P(
        "Cada agente envía su información firmada digitalmente; el backend valida la firma, "
        "almacena los datos, ejecuta tareas periódicas (verificación de dominios, anomalías de "
        "seguridad, respaldos) y genera análisis con IA. El portal web consulta esta información "
        "para mostrar el estado en tiempo real, generar reportes y enviar alertas por email y Telegram.",
        fontName=T.FONT, fontSize=8.5, textColor=T.MUTED, leading=13))
    story.append(T.gap(6))
    story.append(T.P(
        "<b>Stack tecnológico:</b> Django 5 · PostgreSQL · Celery/Redis · HTMX + Tailwind · "
        "ReportLab (PDF) · Railway (hosting) · Claude API (Anthropic)",
        fontName=T.FONT, fontSize=8, textColor=T.MUTED, leading=12))

    # Módulos
    story.append(PageBreak())
    story += T.section("Monitoreo de Infraestructura", "Visibilidad continua del estado de cada equipo")
    story.append(module_grid([
        module_card("Telemetría en Tiempo Real",
                    "CPU, RAM, disco, red, temperatura y GPU (NVIDIA/AMD/Intel) capturados "
                    "cada 60 segundos, con historial y gráficos de tendencia.", T.BRAND),
        module_card("Monitor de Flota en Vivo",
                    "Vista consolidada de todos los equipos de un cliente, con actualización "
                    "automática cada 5 segundos y alertas visuales por umbral.", T.BRAND),
        module_card("Alertas de Conectividad",
                    "Si un equipo deja de reportar, se crea un incidente automático con "
                    "diagnóstico por IA y notificación; al reconectar, se avisa la duración de la caída.", T.AMBER),
        module_card("Reportes Automatizados (PDF)",
                    "Reportes diarios, semanales y mensuales por equipo o cliente, con "
                    "resumen narrativo generado por IA, listos para compartir.", T.BRAND),
    ]))
    story.append(T.gap(14))

    story += T.section("Seguridad Integral", "Postura de seguridad de equipos, M365, dominios y software")
    story.append(module_grid([
        module_card("Postura Microsoft 365",
                    "Secure Score, cobertura de MFA por usuario y estado general de "
                    "seguridad del tenant, con análisis y recomendaciones por IA.", T.RED),
        module_card("Certificados SSL y Dominios",
                    "Verificación de vencimiento de dominios (WHOIS) y certificados "
                    "SSL, con alertas anticipadas por email y Telegram (7 días o menos).", T.RED),
        module_card("Detección de Anomalías del Sistema",
                    "El agente detecta cambios en administradores locales, programas de "
                    "inicio y tareas programadas, generando alertas según severidad.", T.RED),
        module_card("Monitoreo de Inicios de Sesión",
                    "Analiza los accesos a Microsoft 365 y detecta países nuevos, viajes "
                    "imposibles y accesos de alto riesgo.", T.RED),
        module_card("Inventario de Software y CVE",
                    "Catálogo completo del software instalado por equipo, con detección de "
                    "cambios y análisis de vulnerabilidades (CVE) asistido por IA.", T.RED),
        module_card("2FA y Registro de Auditoría",
                    "Autenticación de dos factores (TOTP) para el acceso al panel, y "
                    "registro de auditoría de inicios de sesión y accesos.", T.RED),
    ]))
    story.append(T.gap(14))

    story += T.section("Notificaciones y Continuidad", "Comunicación inmediata y respaldo de la información")
    story.append(module_grid([
        module_card("Alertas Multi-canal",
                    "Notificaciones por email para todos los eventos, y por Telegram para "
                    "los eventos críticos (equipos offline, anomalías graves, vencimientos).", T.GREEN),
        module_card("Respaldo Automático",
                    "Copia de seguridad semanal de la base de datos, comprimida y enviada "
                    "automáticamente por correo al equipo técnico.", T.GREEN),
        module_card("Comunicación Segura (HMAC)",
                    "Cada envío del agente al servidor está firmado digitalmente "
                    "(HMAC-SHA256), evitando suplantación de telemetría.", T.GREEN),
        module_card("Encabezados de Seguridad Web",
                    "Política de seguridad de contenido (CSP) y cabeceras HTTP "
                    "endurecidas en todo el portal.", T.GREEN),
    ]))
    story.append(T.gap(14))

    story += T.section("Gestión y Colaboración", "Herramientas para el equipo técnico y para el cliente final")
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

    # Beneficios
    story.append(T.gap(14))
    story += T.section("Beneficios", "Valor para el equipo técnico y para los clientes finales")
    benefits = Table([[
        benefit_column("Para el equipo técnico (MSP)", T.INK, [
            "Visibilidad centralizada de todos los clientes en un solo panel.",
            "Detección proactiva de problemas antes de que el cliente los reporte.",
            "Automatización de reportes — menos trabajo manual y más consistencia.",
            "Diferenciación: ofrecer seguridad gestionada como servicio premium.",
            "Escalable: incorporar nuevos clientes y equipos sin fricción.",
            "Alertas críticas inmediatas vía Telegram, sin depender solo del email.",
        ]),
        benefit_column("Para los clientes finales", T.BRAND, [
            "Transparencia total: portal propio con su estado en tiempo real.",
            "Reportes profesionales en PDF, listos para presentar a directorio.",
            "Menos incidentes gracias a la detección y corrección temprana.",
            "Cumplimiento y trazabilidad: auditoría de accesos y cambios.",
            "Continuidad asegurada con respaldo automático de información.",
            "Comunicación inmediata ante eventos críticos de seguridad.",
        ]),
    ]], colWidths=[T.CW * 0.485, T.CW * 0.485])
    benefits.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (1, 0), (1, 0), 8), ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(benefits)
    story.append(T.gap(16))
    story.append(T.P(
        f"<b>{company}</b> reúne en una sola plataforma lo que normalmente requeriría varias "
        f"herramientas independientes — monitoreo de infraestructura, seguridad gestionada, "
        f"gestión de incidentes y reportería — con análisis asistido por IA en cada módulo "
        f"clave, entregando una postura de seguridad y disponibilidad medible y "
        f"comunicable a cada cliente.",
        fontName=T.FONT, fontSize=9, textColor=T.BODY, leading=14))

    footer = T.make_footer(company, support)
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    pdf = buf.getvalue()
    buf.close()
    return pdf
