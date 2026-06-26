"""
Sentinel XO — Pronóstico de Capacidad
=====================================
Estima cuándo un disco o la RAM de un equipo alcanzará 90% y 100%, ajustando
una recta por mínimos cuadrados sobre el histórico de TelemetrySnapshot.

Determinístico (sin IA). Reutiliza los snapshots que la vista ya consulta:
NO genera queries adicionales si se le pasan los snapshots.

Uso desde la vista device_detail_live:

    from core.capacity_forecast import forecast_device
    forecast = forecast_device(device, snapshots)   # snapshots ya consultados
    # ... "forecast": forecast en el contexto
"""
import logging
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger("perseus")

MIN_SAMPLES    = 6       
WINDOW_DAYS    = 14      
SPARK_POINTS   = 24       
FLAT_SLOPE     = 0.05     
WARN_THRESHOLD = 90.0
FULL_THRESHOLD = 100.0
SAFETY_CAP     = 5000     


def _linreg(xs, ys):
    """Mínimos cuadrados → (pendiente, intercepto). xs en días, ys en %."""
    n = len(xs)
    if n < 2:
        return 0.0, (ys[-1] if ys else 0.0)
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0, my
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den
    intercept = my - slope * mx
    return slope, intercept


def _spark(ys, width=100, height=26):
    """Genera los puntos de un polyline SVG normalizado a 0–100% en Y."""
    if len(ys) < 2:
        return ""
    if len(ys) > SPARK_POINTS:
        step = len(ys) / SPARK_POINTS
        ys = [ys[int(i * step)] for i in range(SPARK_POINTS)]
    n = len(ys)
    pts = []
    for i, v in enumerate(ys):
        x = (i / (n - 1)) * width
        y = height - (max(0.0, min(100.0, v)) / 100.0) * height
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _project(series, last_pct):
    """
    series: lista de (días_relativos, pct). Devuelve dict con tendencia y
    días hasta 90% y 100%.
    """
    xs = [p[0] for p in series]
    ys = [p[1] for p in series]
    slope, intercept = _linreg(xs, ys)      
    last_x = xs[-1]

    def days_to(threshold):
        if last_pct >= threshold:
            return 0         
        if slope <= FLAT_SLOPE:
            return None       
        x_hit = (threshold - intercept) / slope
        days = x_hit - last_x
        return max(0, round(days)) if days >= 0 else None

    if slope <= -FLAT_SLOPE:
        trend = "bajando"
    elif slope < FLAT_SLOPE:
        trend = "estable"
    else:
        trend = "subiendo"

    return {
        "trend":        trend,
        "slope_day":    round(slope, 3),
        "days_to_warn": days_to(WARN_THRESHOLD),
        "days_to_full": days_to(FULL_THRESHOLD),
    }


def _level(res):
    """Nivel de urgencia según el horizonte más cercano."""
    d = res["days_to_warn"] if res["days_to_warn"] is not None else res["days_to_full"]
    if res["current"] >= FULL_THRESHOLD:
        return "critical"
    if d is None:
        return "ok"
    if d <= 7:
        return "critical"
    if d <= 30:
        return "warning"
    return "ok"


def _latest_attr(snaps, attr):
    for s in reversed(snaps):
        v = getattr(s, attr, None)
        if v:
            return v
    return None


def forecast_device(device, snapshots=None, window_days=WINDOW_DAYS):
    """
    Calcula el pronóstico de disco(s) + RAM de un equipo.

    snapshots: lista ya consultada (cualquier orden; se ordena internamente).
    Si es None, se consulta aquí.
    """
    now = timezone.now()
    cutoff = now - timedelta(days=window_days)

    if snapshots is None:
        snapshots = list(
            device.snapshots
            .filter(captured_at__gte=cutoff)
            .only("captured_at", "ram_used_percent", "ram_total_gb", "disk_usage")
            .order_by("-captured_at")[:SAFETY_CAP]
        )

    snaps = sorted(
        [s for s in snapshots if s.captured_at and s.captured_at >= cutoff],
        key=lambda s: s.captured_at,
    )

    resources = []

    # ── RAM ──────────────────────────────────────────────────────────────
    ram_series = []
    ram_vals = []
    for s in snaps:
        if s.ram_used_percent is not None:
            d = (s.captured_at - cutoff).total_seconds() / 86400.0
            ram_series.append((d, float(s.ram_used_percent)))
            ram_vals.append(float(s.ram_used_percent))
    if len(ram_series) >= MIN_SAMPLES:
        last_pct = ram_series[-1][1]
        proj = _project(ram_series, last_pct)
        res = {
            "kind": "ram", "name": "RAM",
            "current": round(last_pct, 1),
            "total_gb": _latest_attr(snaps, "ram_total_gb"),
            "spark": _spark(ram_vals),
            **proj,
        }
        res["level"] = _level(res)
        resources.append(res)

    # ── Discos ───────────────────────────────────────────────────────────
    disk_series = {}
    disk_vals   = {}
    disk_total  = {}
    for s in snaps:
        for disk in (s.disk_usage or []):
            mp = disk.get("mountpoint") or disk.get("device") or "?"
            up = disk.get("used_percent")
            if up is None:
                continue
            d = (s.captured_at - cutoff).total_seconds() / 86400.0
            disk_series.setdefault(mp, []).append((d, float(up)))
            disk_vals.setdefault(mp, []).append(float(up))
            if disk.get("total_gb") is not None:
                disk_total[mp] = disk.get("total_gb")

    for mp, series in disk_series.items():
        if len(series) < MIN_SAMPLES:
            continue
        last_pct = series[-1][1]
        proj = _project(series, last_pct)
        res = {
            "kind": "disk", "name": f"Disco {mp}",
            "current": round(last_pct, 1),
            "total_gb": disk_total.get(mp),
            "spark": _spark(disk_vals[mp]),
            **proj,
        }
        res["level"] = _level(res)
        resources.append(res)

    order = {"critical": 0, "warning": 1, "ok": 2}
    resources.sort(key=lambda r: (order.get(r["level"], 3),
                                  r["days_to_warn"] if r["days_to_warn"] is not None else 9999))

    worst = resources[0]["level"] if resources else "none"
    return {
        "resources": resources,
        "worst": worst,
        "samples": len(snaps),
        "window_days": window_days,
        "enough_data": bool(resources),
    }
