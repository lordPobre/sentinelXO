"""
Sentinel XO — Reporte PDF individual por dispositivo
Muestra promedios diarios o semanales de CPU, RAM, temperatura y GPU.
"""
import io
from datetime import datetime, timedelta
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

# ── Paleta (misma que generator.py) ───────────────────────────────────────────
C_DARK   = colors.HexColor("#0f172a")
C_BLUE   = colors.HexColor("#2563eb")
C_SLATE8 = colors.HexColor("#1e293b")
C_SLATE5 = colors.HexColor("#64748b")
C_SLATE3 = colors.HexColor("#e2e8f0")
C_SLATE0 = colors.HexColor("#f8fafc")
C_WHITE  = colors.white
C_GREEN  = colors.HexColor("#10b981")
C_AMBER  = colors.HexColor("#f59e0b")
C_RED    = colors.HexColor("#ef4444")
C_PURPLE = colors.HexColor("#8b5cf6")

MESES = {
    1:"enero", 2:"febrero", 3:"marzo", 4:"abril", 5:"mayo", 6:"junio",
    7:"julio", 8:"agosto", 9:"septiembre", 10:"octubre", 11:"noviembre", 12:"diciembre"
}


# ── Helpers ────────────────────────────────────────────────────────────────────
def ps(name, **kw):
    d = dict(fontName="Helvetica", fontSize=9, textColor=C_SLATE5, leading=13)
    d.update(kw)
    return ParagraphStyle(name, **d)

def th(txt, align=TA_LEFT):
    return Paragraph(f"<b>{txt}</b>", ps(f"TH_{txt[:8]}",
        fontName="Helvetica-Bold", fontSize=7.5, textColor=C_WHITE,
        letterSpacing=0.3, leading=10, alignment=align))

def td(txt, bold=False, color=C_SLATE8, size=8.5, align=TA_LEFT):
    return Paragraph(str(txt), ps(f"TD_{str(txt)[:8]}",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, textColor=color, leading=12, alignment=align))

def metric_bar(pct, bar_color, width=60):
    """Barra de progreso horizontal."""
    if pct is None:
        return td("—", color=C_SLATE5)
    pct = max(0, min(100, pct))
    d = Drawing(width + 40, 10)
    d.add(Rect(0, 2, width, 6, fillColor=C_SLATE3, strokeColor=None, rx=3, ry=3))
    if pct > 0:
        d.add(Rect(0, 2, width * pct / 100, 6, fillColor=bar_color, strokeColor=None, rx=3, ry=3))
    return d

def bar_with_label(pct, bar_color, width=60):
    """Barra + número en tabla interna."""
    if pct is None:
        return td("—", color=C_SLATE5)
    pct_rounded = round(pct, 1)
    return Table([
        [metric_bar(pct, bar_color, width)],
        [Paragraph(f"{pct_rounded}%", ps(f"bl{pct_rounded}",
            fontSize=7.5, textColor=C_SLATE5, leading=9))],
    ], colWidths=[width + 40])

def temp_cell(val):
    """Celda de temperatura con color."""
    if val is None:
        return td("—", color=C_SLATE5)
    val = round(val, 1)
    if val >= 85:   c = C_RED
    elif val >= 70: c = C_AMBER
    else:           c = C_GREEN
    return td(f"{val}°C", bold=True, color=c)

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

TH_STYLE = [
    ("BACKGROUND",    (0,0), (-1,0),  C_SLATE8),
    ("TEXTCOLOR",     (0,0), (-1,0),  C_WHITE),
    ("FONTNAME",      (0,0), (-1,0),  "Helvetica-Bold"),
    ("FONTSIZE",      (0,0), (-1,-1), 8.5),
    ("TOPPADDING",    (0,0), (-1,0),  9),
    ("BOTTOMPADDING", (0,0), (-1,0),  9),
    ("TOPPADDING",    (0,1), (-1,-1), 9),
    ("BOTTOMPADDING", (0,1), (-1,-1), 9),
    ("LEFTPADDING",   (0,0), (-1,-1), 10),
    ("RIGHTPADDING",  (0,0), (-1,-1), 10),
    ("ROWBACKGROUNDS",(0,1), (-1,-1), [C_WHITE, C_SLATE0]),
    ("LINEBELOW",     (0,0), (-1,-1), 0.4, C_SLATE3),
    ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
]

def footer_cb(company, support):
    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_SLATE5)
        canvas.drawString(ML, 12*mm, f"{company}  ·  {support}  ·  Confidencial")
        canvas.drawRightString(PAGE_W - MR, 12*mm, f"Página {doc.page}")
        canvas.restoreState()
    return _footer


# ── Lógica de agrupación ───────────────────────────────────────────────────────
def _avg(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None

def _extract_cpu_temp(temperatures):
    """Extrae temperatura de CPU desde el JSON de temperaturas."""
    if not temperatures:
        return None
    keywords = ["cpu", "processor", "package", "core", "tdie", "tctl"]
    # Primero buscar coincidencia específica de CPU
    for t in temperatures:
        label = t.get("label", "").lower()
        if any(k in label for k in keywords):
            v = t.get("current")
            if v is not None:
                return float(v)
    # Si no, primera temperatura disponible
    first = temperatures[0].get("current")
    return float(first) if first is not None else None

def build_daily_averages(snapshots_qs, start_date, end_date, has_gpu):
    """
    Agrupa snapshots por día y calcula promedios.
    Retorna lista de dicts ordenada por fecha.
    """
    from django.db.models.functions import TruncDate
    from django.db.models import Avg

    # Promedios básicos agrupados por día
    daily = (
        snapshots_qs
        .filter(captured_at__date__gte=start_date, captured_at__date__lte=end_date)
        .annotate(day=TruncDate("captured_at"))
        .values("day")
        .annotate(
            avg_cpu=Avg("cpu_percent"),
            avg_ram=Avg("ram_used_percent"),
            avg_gpu_usage=Avg("gpu_usage_percent"),
            avg_gpu_mem=Avg("gpu_memory_used_percent"),
            avg_gpu_temp=Avg("gpu_temp_celsius"),
            count=models_Count("id"),
        )
        .order_by("day")
    )

    # Temperatura CPU viene del JSON — hay que hacerlo en Python
    # Primero traer snapshots agrupados por día con su temperatura
    result = []
    for row in daily:
        day = row["day"]
        # Obtener temps de ese día para calcular promedio CPU temp
        day_snaps = snapshots_qs.filter(captured_at__date=day).values_list("temperatures", flat=True)
        cpu_temps = [_extract_cpu_temp(t) for t in day_snaps]
        avg_cpu_temp = _avg(cpu_temps)

        result.append({
            "period":       day.strftime("%d/%m/%Y"),
            "samples":      row["count"],
            "avg_cpu":      round(row["avg_cpu"], 1) if row["avg_cpu"] is not None else None,
            "avg_ram":      round(row["avg_ram"], 1) if row["avg_ram"] is not None else None,
            "avg_cpu_temp": avg_cpu_temp,
            "avg_gpu_usage": round(row["avg_gpu_usage"], 1) if row["avg_gpu_usage"] is not None else None,
            "avg_gpu_mem":   round(row["avg_gpu_mem"], 1) if row["avg_gpu_mem"] is not None else None,
            "avg_gpu_temp":  round(row["avg_gpu_temp"], 1) if row["avg_gpu_temp"] is not None else None,
        })
    return result

def build_weekly_averages(snapshots_qs, start_date, end_date, has_gpu):
    """
    Agrupa snapshots por semana ISO y calcula promedios.
    """
    from django.db.models.functions import TruncWeek
    from django.db.models import Avg

    weekly = (
        snapshots_qs
        .filter(captured_at__date__gte=start_date, captured_at__date__lte=end_date)
        .annotate(week=TruncWeek("captured_at"))
        .values("week")
        .annotate(
            avg_cpu=Avg("cpu_percent"),
            avg_ram=Avg("ram_used_percent"),
            avg_gpu_usage=Avg("gpu_usage_percent"),
            avg_gpu_mem=Avg("gpu_memory_used_percent"),
            avg_gpu_temp=Avg("gpu_temp_celsius"),
            count=models_Count("id"),
        )
        .order_by("week")
    )

    result = []
    for row in weekly:
        week_start = row["week"].date() if hasattr(row["week"], "date") else row["week"]
        week_end   = week_start + timedelta(days=6)
        label      = f"{week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}"

        day_snaps = snapshots_qs.filter(
            captured_at__date__gte=week_start,
            captured_at__date__lte=week_end,
        ).values_list("temperatures", flat=True)
        cpu_temps = [_extract_cpu_temp(t) for t in day_snaps]
        avg_cpu_temp = _avg(cpu_temps)

        result.append({
            "period":       label,
            "samples":      row["count"],
            "avg_cpu":      round(row["avg_cpu"], 1) if row["avg_cpu"] is not None else None,
            "avg_ram":      round(row["avg_ram"], 1) if row["avg_ram"] is not None else None,
            "avg_cpu_temp": avg_cpu_temp,
            "avg_gpu_usage": round(row["avg_gpu_usage"], 1) if row["avg_gpu_usage"] is not None else None,
            "avg_gpu_mem":   round(row["avg_gpu_mem"], 1) if row["avg_gpu_mem"] is not None else None,
            "avg_gpu_temp":  round(row["avg_gpu_temp"], 1) if row["avg_gpu_temp"] is not None else None,
        })
    return result

# Import Count con alias para evitar conflicto de nombre
def models_Count(field):
    from django.db.models import Count
    return Count(field)


# ── Función principal ──────────────────────────────────────────────────────────
def build_device_report_pdf(device, year: int, month: int,
                             granularity: str = "daily") -> tuple[bytes, dict]:
    """
    Genera reporte PDF individual para un dispositivo.

    Args:
        device:      instancia de HardwareDevice
        year:        año del reporte
        month:       mes del reporte
        granularity: "daily" | "weekly"

    Returns:
        (pdf_bytes, summary_dict)
    """
    from dateutil.relativedelta import relativedelta
    from django.conf import settings
    from core.models import TelemetrySnapshot

    period_start = timezone.make_aware(datetime(year, month, 1))
    period_end   = period_start + relativedelta(months=1)
    month_name   = MESES.get(month, str(month)).capitalize()

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    snapshots = TelemetrySnapshot.objects.filter(
        device=device,
        captured_at__gte=period_start,
        captured_at__lt=period_end,
    )
    total_snaps = snapshots.count()

    # Detectar si el dispositivo tiene GPU en este período
    has_gpu = snapshots.filter(gpu_name__gt="").exists()
    gpu_name = ""
    if has_gpu:
        snap_with_gpu = snapshots.filter(gpu_name__gt="").values_list("gpu_name", flat=True).first()
        gpu_name = snap_with_gpu or ""

    # Construir datos agrupados
    start_date = period_start.date()
    end_date   = (period_end - timedelta(days=1)).date()

    if granularity == "weekly":
        rows = build_weekly_averages(snapshots, start_date, end_date, has_gpu)
        period_label = "Semana"
    else:
        rows = build_daily_averages(snapshots, start_date, end_date, has_gpu)
        period_label = "Día"

    # Promedios globales del período
    def global_avg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    g_cpu      = global_avg("avg_cpu")
    g_ram      = global_avg("avg_ram")
    g_cpu_temp = global_avg("avg_cpu_temp")
    g_gpu_use  = global_avg("avg_gpu_usage")
    g_gpu_temp = global_avg("avg_gpu_temp")

    summary = {
        "device":        device.display_name,
        "period":        f"{year}/{month:02d}",
        "granularity":   granularity,
        "total_samples": total_snaps,
        "avg_cpu":       g_cpu,
        "avg_ram":       g_ram,
        "avg_cpu_temp":  g_cpu_temp,
        "has_gpu":       has_gpu,
        "gpu_name":      gpu_name,
        "avg_gpu_usage": g_gpu_use,
        "avg_gpu_temp":  g_gpu_temp,
    }

    # ── BUILD PDF ──────────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=ML, rightMargin=MR, topMargin=MT, bottomMargin=MB)
    story = []

    # ── HEADER ────────────────────────────────────────────────────────────────
    gran_label = "Reporte Diario" if granularity == "daily" else "Reporte Semanal"
    hdr = Table([[
        Paragraph(
            f'<font color="white" size="18"><b>{company}</b></font><br/>'
            f'<font color="#cbd5e1" size="9">Plataforma de Monitoreo Avanzado</font>',
            ps("hL", fontName="Helvetica-Bold", fontSize=18, textColor=C_WHITE, leading=22)),
        Paragraph(
            f'<font color="#93c5fd" size="9">{gran_label} de Rendimiento</font><br/>'
            f'<font color="white" size="18"><b>{month_name} {year}</b></font>',
            ps("hR", fontSize=9, textColor=colors.HexColor("#93c5fd"),
               leading=22, alignment=TA_RIGHT)),
    ]], colWidths=[CW * 0.55, CW * 0.45])
    hdr.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_DARK),
        ("LEFTPADDING",   (0,0),(-1,-1), 20),
        ("RIGHTPADDING",  (0,0),(-1,-1), 20),
        ("TOPPADDING",    (0,0),(-1,-1), 20),
        ("BOTTOMPADDING", (0,0),(-1,-1), 20),
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
    ]))
    story.append(hdr)
    accent = Drawing(CW, 4)
    accent.add(Rect(0, 0, CW, 4, fillColor=C_BLUE, strokeColor=None))
    story.append(accent)
    story.append(Spacer(1, 4))

    # ── INFO DISPOSITIVO ──────────────────────────────────────────────────────
    def info_cell(label, value, size=9, bold=False):
        return Table([
            [Paragraph(label, ps(f"il{label[:4]}", fontName="Helvetica-Bold",
                fontSize=7, textColor=C_SLATE5, letterSpacing=0.5, leading=10))],
            [Paragraph(str(value), ps(f"iv{str(value)[:4]}",
                fontName="Helvetica-Bold" if bold else "Helvetica",
                fontSize=size, textColor=C_SLATE8, leading=size + 4))],
        ], colWidths=[None])

    dev_info = Table([[
        info_cell("DISPOSITIVO", device.display_name, size=13, bold=True),
        info_cell("TIPO",        device.get_device_type_display()),
        info_cell("SISTEMA",     device.os or "—"),
        info_cell("CLIENTE",     device.client.company_name),
        info_cell("GENERADO",    timezone.now().strftime("%d/%m/%Y %H:%M")),
    ]], colWidths=[CW*0.28, CW*0.15, CW*0.20, CW*0.20, CW*0.17])
    dev_info.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_SLATE0),
        ("LEFTPADDING",   (0,0),(-1,-1), 12),
        ("RIGHTPADDING",  (0,0),(-1,-1), 12),
        ("TOPPADDING",    (0,0),(-1,-1), 12),
        ("BOTTOMPADDING", (0,0),(-1,-1), 12),
        ("LINEAFTER",     (0,0),(3,0),   0.5, C_SLATE3),
        ("LINEBELOW",     (0,0),(-1,-1), 3,   C_BLUE),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    story.append(dev_info)
    story.append(Spacer(1, 22))

    # ── KPIs del período ──────────────────────────────────────────────────────
    story += section_header("Resumen del Período",
        f"{total_snaps:,} muestras registradas en {month_name} {year}")

    def kpi_color_pct(val, warn=70, crit=90):
        if val is None: return "#64748b"
        return "#10b981" if val < warn else "#f59e0b" if val < crit else "#ef4444"

    def kpi_color_temp(val):
        if val is None: return "#64748b"
        return "#10b981" if val < 70 else "#f59e0b" if val < 85 else "#ef4444"

    kpi_list = [
        ("CPU PROMEDIO",  f"{g_cpu}%" if g_cpu is not None else "—",
         "uso medio del período",  kpi_color_pct(g_cpu)),
        ("RAM PROMEDIO",  f"{g_ram}%" if g_ram is not None else "—",
         "uso medio del período",  kpi_color_pct(g_ram)),
        ("TEMP. CPU",     f"{g_cpu_temp}°C" if g_cpu_temp is not None else "—",
         "temperatura promedio",   kpi_color_temp(g_cpu_temp)),
    ]
    if has_gpu:
        kpi_list.append((
            "GPU PROMEDIO", f"{g_gpu_use}%" if g_gpu_use is not None else "—",
            "uso medio del período", kpi_color_pct(g_gpu_use)
        ))
        kpi_list.append((
            "TEMP. GPU", f"{g_gpu_temp}°C" if g_gpu_temp is not None else "—",
            "temperatura promedio", kpi_color_temp(g_gpu_temp)
        ))
    else:
        kpi_list.append(("MUESTRAS", str(total_snaps), "lecturas del período", "#2563eb"))
        kpi_list.append(("GPU", "No detectada", "sin datos de GPU", "#64748b"))

    KW = CW / 5
    kpi_cells = []
    for lbl_t, val_t, sub_t, col in kpi_list:
        kpi_cells.append(Table([
            [Paragraph(lbl_t, ps(f"kl{lbl_t[:4]}", fontName="Helvetica-Bold",
                fontSize=7, textColor=C_SLATE5, letterSpacing=0.3,
                leading=9, alignment=TA_CENTER))],
            [Paragraph(f"<b>{val_t}</b>", ps(f"kv{lbl_t[:4]}", fontName="Helvetica-Bold",
                fontSize=20, textColor=colors.HexColor(col),
                leading=24, alignment=TA_CENTER))],
            [Paragraph(sub_t, ps(f"ks{lbl_t[:4]}", fontSize=7.5,
                textColor=C_SLATE5, leading=10, alignment=TA_CENTER))],
        ], colWidths=[KW - 22]))

    kpi_row = Table([kpi_cells], colWidths=[KW] * 5)
    kpi_row.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), C_SLATE0),
        ("LINEAFTER",     (0,0),(3,0),   0.5, C_SLATE3),
        ("LINEBELOW",     (0,0),(-1,-1), 3,   C_BLUE),
        ("LEFTPADDING",   (0,0),(-1,-1), 11),
        ("RIGHTPADDING",  (0,0),(-1,-1), 11),
        ("TOPPADDING",    (0,0),(-1,-1), 14),
        ("BOTTOMPADDING", (0,0),(-1,-1), 14),
        ("VALIGN",        (0,0),(-1,-1), "TOP"),
    ]))
    story.append(kpi_row)
    story.append(Spacer(1, 22))

    # ── TABLA DE PROMEDIOS CPU + RAM + TEMP CPU ────────────────────────────────
    story += section_header(
        f"Rendimiento {'Diario' if granularity == 'daily' else 'Semanal'} — CPU y RAM",
        f"Promedios {'por día' if granularity == 'daily' else 'por semana'} · "
        f"{len(rows)} período{'s' if len(rows) != 1 else ''}")

    if rows:
        cpu_ram_rows = [[
            th(period_label),
            th("CPU Promedio"),
            th("RAM Promedio"),
            th("Temp. CPU"),
            th("Muestras", TA_RIGHT),
        ]]
        for r in rows:
            cpu_c  = C_GREEN if (r["avg_cpu"] or 0) < 70 else C_AMBER if (r["avg_cpu"] or 0) < 90 else C_RED
            ram_c  = C_GREEN if (r["avg_ram"] or 0) < 70 else C_AMBER if (r["avg_ram"] or 0) < 90 else C_RED
            cpu_ram_rows.append([
                td(r["period"], bold=True),
                bar_with_label(r["avg_cpu"], cpu_c, 65),
                bar_with_label(r["avg_ram"], ram_c, 65),
                temp_cell(r["avg_cpu_temp"]),
                td(str(r["samples"]), color=C_SLATE5, align=TA_RIGHT),
            ])
        t = Table(cpu_ram_rows,
                  colWidths=[3.5*cm, 4.5*cm, 4.5*cm, 2.5*cm, 2.5*cm],
                  repeatRows=1)
        t.setStyle(TableStyle(TH_STYLE))
        story.append(t)
    else:
        story.append(Paragraph(
            "Sin datos para este período.",
            ps("nd", fontSize=9, textColor=C_SLATE5)))
    story.append(Spacer(1, 18))

    # ── TABLA GPU (solo si hay datos) ─────────────────────────────────────────
    if has_gpu and any(r.get("avg_gpu_usage") is not None for r in rows):
        story += section_header(
            f"Rendimiento {'Diario' if granularity == 'daily' else 'Semanal'} — GPU",
            f"{gpu_name}  ·  promedios {'por día' if granularity == 'daily' else 'por semana'}")

        gpu_rows = [[
            th(period_label),
            th("GPU Uso"),
            th("VRAM Uso"),
            th("Temp. GPU"),
            th("Muestras", TA_RIGHT),
        ]]
        for r in rows:
            gpu_c  = C_GREEN if (r["avg_gpu_usage"] or 0) < 70 else C_AMBER if (r["avg_gpu_usage"] or 0) < 90 else C_RED
            gmem_c = C_GREEN if (r["avg_gpu_mem"] or 0) < 70 else C_AMBER if (r["avg_gpu_mem"] or 0) < 90 else C_RED
            gpu_rows.append([
                td(r["period"], bold=True),
                bar_with_label(r["avg_gpu_usage"], gpu_c, 65),
                bar_with_label(r["avg_gpu_mem"], gmem_c, 65),
                temp_cell(r["avg_gpu_temp"]),
                td(str(r["samples"]), color=C_SLATE5, align=TA_RIGHT),
            ])
        t = Table(gpu_rows,
                  colWidths=[3.5*cm, 4.5*cm, 4.5*cm, 2.5*cm, 2.5*cm],
                  repeatRows=1)
        t.setStyle(TableStyle(TH_STYLE))
        story.append(t)
        story.append(Spacer(1, 18))

    # ── NOTAS FINALES ─────────────────────────────────────────────────────────
    notes = []
    if not has_gpu:
        notes.append("• GPU no detectada en este dispositivo durante el período reportado. "
                     "Para activar monitoreo GPU instalar pynvml (NVIDIA) u OpenHardwareMonitor (AMD/Intel).")
    if g_cpu_temp is None:
        notes.append("• Temperatura CPU no disponible. "
                     "Instalar OpenHardwareMonitor y WMI para activar sensores en Windows.")
    if notes:
        story.append(Spacer(1, 6))
        story += section_header("Notas")
        for note in notes:
            story.append(Paragraph(note, ps("note", fontSize=8, textColor=C_SLATE5, leading=12)))
            story.append(Spacer(1, 4))

    doc.build(story, onFirstPage=footer_cb(company, support),
              onLaterPages=footer_cb(company, support))
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes, summary
