"""
Sentinel XO — Reporte PDF individual por dispositivo (diario/semanal)
=====================================================================
Reconstruido sobre `reports.pdf_theme`. Muestra promedios de CPU, RAM,
temperatura y GPU por día o por semana.

- `build_device_report_pdf(device, year, month, granularity)` → datos reales.
- `compose_device_story(data)` → presentación pura (sin Django).
"""
import io
from datetime import timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Spacer

from reports import pdf_theme as T
from reports.cover import render_with_cover


# ── Helpers de datos (puros) ─────────────────────────────────────────────────
def _avg(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _extract_cpu_temp(temperatures):
    if not temperatures:
        return None
    keywords = ["cpu", "processor", "package", "core", "tdie", "tctl"]
    for t in temperatures:
        label = (t.get("label", "") or "").lower()
        if any(k in label for k in keywords):
            v = t.get("current")
            if v is not None:
                return float(v)
    first = temperatures[0].get("current")
    return float(first) if first is not None else None


def _build_averages(snapshots_qs, start_date, end_date, mode):
    """mode: 'daily' | 'weekly'. Devuelve lista de filas con promedios."""
    from django.db.models import Avg, Count
    from django.db.models.functions import TruncDate, TruncWeek

    trunc = TruncDate("captured_at") if mode == "daily" else TruncWeek("captured_at")
    key = "day" if mode == "daily" else "week"
    agg = (
        snapshots_qs
        .filter(captured_at__date__gte=start_date, captured_at__date__lte=end_date)
        .annotate(**{key: trunc})
        .values(key)
        .annotate(
            avg_cpu=Avg("cpu_percent"),
            avg_ram=Avg("ram_used_percent"),
            avg_gpu_usage=Avg("gpu_usage_percent"),
            avg_gpu_mem=Avg("gpu_memory_used_percent"),
            avg_gpu_temp=Avg("gpu_temp_celsius"),
            count=Count("id"),
        )
        .order_by(key)
    )

    def r1(v):
        return round(v, 1) if v is not None else None

    result = []
    for row in agg:
        if mode == "daily":
            day = row["day"]
            label = day.strftime("%d/%m/%Y")
            d_snaps = snapshots_qs.filter(captured_at__date=day).values_list("temperatures", flat=True)
        else:
            week_start = row["week"].date() if hasattr(row["week"], "date") else row["week"]
            week_end = week_start + timedelta(days=6)
            label = f"{week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}"
            d_snaps = snapshots_qs.filter(
                captured_at__date__gte=week_start, captured_at__date__lte=week_end
            ).values_list("temperatures", flat=True)

        cpu_temps = [_extract_cpu_temp(t) for t in d_snaps]
        result.append({
            "period": label,
            "samples": row["count"],
            "cpu": r1(row["avg_cpu"]),
            "ram": r1(row["avg_ram"]),
            "cpu_temp": _avg(cpu_temps),
            "gpu_usage": r1(row["avg_gpu_usage"]),
            "gpu_mem": r1(row["avg_gpu_mem"]),
            "gpu_temp": r1(row["avg_gpu_temp"]),
        })
    return result


# ════════════════════════════════════════════════════════════════════════════
#  COMPOSICIÓN (pura)
# ════════════════════════════════════════════════════════════════════════════
def compose_device_story(d: dict) -> list:
    daily = d["granularity"] == "daily"
    per_word = "Diario" if daily else "Semanal"
    per_col = "Día" if daily else "Semana"
    story = []

    story.append(T.info_strip([
        ("Dispositivo", d["device_name"], True),
        ("Tipo",        d["device_type"]),
        ("Sistema",     d["os"] or "—"),
        ("Cliente",     d["client_name"]),
        ("Generado",    d["generated_at"]),
    ]))
    story.append(T.gap(20))

    # KPIs
    k = d["kpis"]
    story += T.section("Resumen del Período",
                       f'{d["total_samples"]:,} muestras registradas en {d["month_name"]} {d["year"]}')
    cards = [
        ("CPU promedio",  f'{k["cpu"]}%' if k["cpu"] is not None else "—", "uso medio", T.status_color(k["cpu"])),
        ("RAM promedio",  f'{k["ram"]}%' if k["ram"] is not None else "—", "uso medio", T.status_color(k["ram"])),
        ("Temp. CPU",     f'{k["cpu_temp"]}°C' if k["cpu_temp"] is not None else "—", "temperatura", T.temp_color(k["cpu_temp"])),
    ]
    if d["has_gpu"]:
        cards.append(("GPU promedio", f'{k["gpu_usage"]}%' if k["gpu_usage"] is not None else "—", "uso medio", T.status_color(k["gpu_usage"])))
        cards.append(("Temp. GPU", f'{k["gpu_temp"]}°C' if k["gpu_temp"] is not None else "—", "temperatura", T.temp_color(k["gpu_temp"])))
    else:
        cards.append(("Muestras", f'{d["total_samples"]:,}', "lecturas del período", T.BRAND))
    story.append(T.kpi_cards(cards))
    story.append(T.gap(18))

    rows_data = d["rows"]

    # CPU/RAM
    story += T.section(f"Rendimiento {per_word} — CPU y RAM",
                       f'Promedios por {"día" if daily else "semana"} · {len(rows_data)} período{"s" if len(rows_data) != 1 else ""}')
    if rows_data:
        rows = [[T.th(per_col), T.th("CPU promedio"), T.th("RAM promedio"),
                 T.th("Temp. CPU", TA_CENTER), T.th("Muestras", TA_RIGHT)]]
        for r in rows_data:
            rows.append([
                T.td(r["period"], bold=True, mono=True, size=8),
                T.progress(r["cpu"], T.status_color(r["cpu"]), width=70),
                T.progress(r["ram"], T.status_color(r["ram"]), width=70),
                (T.td(f'{r["cpu_temp"]}°C', bold=True, color=T.temp_color(r["cpu_temp"]), align=TA_CENTER)
                 if r["cpu_temp"] is not None else T.td("—", color=T.FAINT, align=TA_CENTER)),
                T.td(str(r["samples"]), color=T.MUTED, align=TA_RIGHT, mono=True),
            ])
        story.append(T.table(rows,
            col_widths=[T.CW*0.24, T.CW*0.24, T.CW*0.24, T.CW*0.15, T.CW*0.13],
            aligns={3: "C", 4: "R"}))
    else:
        story.append(T.empty("Sin datos para este período."))
    story.append(T.gap(18))

    # GPU
    if d["has_gpu"] and any(r.get("gpu_usage") is not None for r in rows_data):
        story += T.section(f"Rendimiento {per_word} — GPU",
                           f'{d["gpu_name"]} · promedios por {"día" if daily else "semana"}')
        rows = [[T.th(per_col), T.th("GPU uso"), T.th("VRAM uso"),
                 T.th("Temp. GPU", TA_CENTER), T.th("Muestras", TA_RIGHT)]]
        for r in rows_data:
            rows.append([
                T.td(r["period"], bold=True, mono=True, size=8),
                T.progress(r["gpu_usage"], T.status_color(r["gpu_usage"]), width=70),
                T.progress(r["gpu_mem"], T.status_color(r["gpu_mem"]), width=70),
                (T.td(f'{r["gpu_temp"]}°C', bold=True, color=T.temp_color(r["gpu_temp"]), align=TA_CENTER)
                 if r["gpu_temp"] is not None else T.td("—", color=T.FAINT, align=TA_CENTER)),
                T.td(str(r["samples"]), color=T.MUTED, align=TA_RIGHT, mono=True),
            ])
        story.append(T.table(rows,
            col_widths=[T.CW*0.24, T.CW*0.24, T.CW*0.24, T.CW*0.15, T.CW*0.13],
            aligns={3: "C", 4: "R"}))
        story.append(T.gap(18))

    # Notas
    if d["notes"]:
        story += T.section("Notas")
        for note in d["notes"]:
            story.append(T.P(note, fontName=T.FONT, fontSize=8, textColor=T.MUTED, leading=12))
            story.append(T.gap(4))

    return story


def _render(data: dict) -> bytes:
    per_word = "Diario" if data["granularity"] == "daily" else "Semanal"
    return render_with_cover(
        company=data["company"], support=data["support"],
        product=data.get("product", "Sentinel XO"),
        kicker=f"Reporte {per_word} de Rendimiento",
        title=data["client_name"],
        subtitle=f'{data["device_name"]} \u00b7 {data["month_name"]} {data["year"]}',
        generated_at=data["generated_at"],
        content_story=compose_device_story(data),
    )


# ════════════════════════════════════════════════════════════════════════════
#  ENTRADA CON DATOS REALES (Django)
# ════════════════════════════════════════════════════════════════════════════
def build_device_report_pdf(device, year: int, month: int,
                            granularity: str = "daily") -> tuple[bytes, dict]:
    from datetime import datetime
    from django.utils import timezone
    from django.conf import settings
    from dateutil.relativedelta import relativedelta
    from core.models import TelemetrySnapshot

    if granularity not in ("daily", "weekly"):
        granularity = "daily"

    period_start = timezone.make_aware(datetime(year, month, 1))
    period_end   = period_start + relativedelta(months=1)
    month_name   = T.MESES.get(month, str(month)).capitalize()

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    snapshots = TelemetrySnapshot.objects.filter(
        device=device, captured_at__gte=period_start, captured_at__lt=period_end)
    total_snaps = snapshots.count()
    has_gpu = snapshots.filter(gpu_name__gt="").exists()
    gpu_name = (snapshots.filter(gpu_name__gt="").values_list("gpu_name", flat=True).first() or "") if has_gpu else ""

    start_date = period_start.date()
    end_date = (period_end - timedelta(days=1)).date()
    rows = _build_averages(snapshots, start_date, end_date, granularity)

    def gavg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    kpis = {
        "cpu": gavg("cpu"), "ram": gavg("ram"), "cpu_temp": gavg("cpu_temp"),
        "gpu_usage": gavg("gpu_usage"), "gpu_temp": gavg("gpu_temp"),
    }

    notes = []
    if not has_gpu:
        notes.append("• GPU no detectada en este dispositivo durante el período reportado. "
                     "Para activar monitoreo GPU instalar pynvml (NVIDIA) u OpenHardwareMonitor (AMD/Intel).")
    if kpis["cpu_temp"] is None:
        notes.append("• Temperatura CPU no disponible. "
                     "Instalar OpenHardwareMonitor y WMI para activar sensores en Windows.")

    data = {
        "company": company, "support": support,
        "device_name": device.display_name,
        "device_type": device.get_device_type_display(),
        "os": device.os or "",
        "client_name": device.client.company_name,
        "generated_at": timezone.localtime(timezone.now()).strftime("%d/%m/%Y %H:%M"),
        "granularity": granularity,
        "month_name": month_name, "year": year,
        "total_samples": total_snaps,
        "has_gpu": has_gpu, "gpu_name": gpu_name,
        "kpis": kpis, "rows": rows, "notes": notes,
    }

    summary = {
        "device": device.display_name, "period": f"{year}/{month:02d}",
        "granularity": granularity, "total_samples": total_snaps,
        "avg_cpu": kpis["cpu"], "avg_ram": kpis["ram"], "avg_cpu_temp": kpis["cpu_temp"],
        "has_gpu": has_gpu, "gpu_name": gpu_name,
        "avg_gpu_usage": kpis["gpu_usage"], "avg_gpu_temp": kpis["gpu_temp"],
    }
    return _render(data), summary