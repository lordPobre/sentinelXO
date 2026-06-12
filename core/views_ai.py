"""
Sentinel XO — Análisis Predictivo con IA (Claude API)
Analiza el historial de telemetría y genera insights inteligentes.
"""
import json
import os
import logging
import urllib.request
import urllib.error
from datetime import timedelta, datetime
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.shortcuts import get_object_or_404

logger = logging.getLogger("sentinel.ai")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-6"


def _extract_cpu_temp(temperatures):
    if not temperatures:
        return None
    keywords = ["cpu", "processor", "package", "core", "tdie", "tctl"]
    for t in temperatures:
        label = t.get("label", "").lower()
        if any(k in label for k in keywords):
            val = t.get("current")
            if val is not None:
                return float(val)
    first = temperatures[0].get("current") if temperatures else None
    return float(first) if first is not None else None


def _build_telemetry_summary(device, snapshots) -> dict:
    """
    Construye un resumen estadístico del historial de telemetría
    optimizado para el contexto de la IA.
    """
    if not snapshots:
        return {}

    cpu_vals   = [s.cpu_percent for s in snapshots if s.cpu_percent is not None]
    ram_vals   = [s.ram_used_percent for s in snapshots if s.ram_used_percent is not None]
    temp_vals  = [_extract_cpu_temp(s.temperatures or []) for s in snapshots]
    temp_vals  = [t for t in temp_vals if t is not None]
    gpu_vals   = [s.gpu_usage_percent for s in snapshots if s.gpu_usage_percent is not None]
    gpu_temps  = [s.gpu_temp_celsius for s in snapshots if s.gpu_temp_celsius is not None]

    def stats(vals):
        if not vals:
            return None
        return {
            "min":  round(min(vals), 1),
            "max":  round(max(vals), 1),
            "avg":  round(sum(vals) / len(vals), 1),
            "last": round(vals[-1], 1),
            "high_count": sum(1 for v in vals if v > 85),
            "critical_count": sum(1 for v in vals if v > 95),
        }

    # Tendencia: comparar primera mitad vs segunda mitad
    def trend(vals):
        if len(vals) < 10:
            return "insuficientes datos"
        mid   = len(vals) // 2
        first = sum(vals[:mid]) / mid
        last  = sum(vals[mid:]) / (len(vals) - mid)
        diff  = last - first
        if diff > 5:   return f"subiendo (+{diff:.1f})"
        if diff < -5:  return f"bajando ({diff:.1f})"
        return "estable"

    # Picos: momentos donde CPU o temperatura estuvieron muy altos
    peaks = []
    for s in snapshots:
        cpu_t = _extract_cpu_temp(s.temperatures or [])
        if (s.cpu_percent and s.cpu_percent > 90) or (cpu_t and cpu_t > 80):
            peaks.append({
                "time": timezone.localtime(s.captured_at).strftime("%d/%m %H:%M"),
                "cpu":  s.cpu_percent,
                "temp": cpu_t,
            })
    peaks = peaks[-5:]  # últimos 5 picos

    # Discos críticos
    disk_alerts = []
    last_snap = snapshots[-1]
    for disk in (last_snap.disk_usage or []):
        if disk.get("used_percent", 0) > 80:
            disk_alerts.append({
                "mount":    disk["mountpoint"],
                "used_pct": disk["used_percent"],
                "total_gb": disk["total_gb"],
            })

    return {
        "device_name":    device.display_name,
        "os":             device.os or "—",
        "device_type":    device.get_device_type_display(),
        "samples":        len(snapshots),
        "period_hours":   round((snapshots[-1].captured_at - snapshots[0].captured_at
                                ).total_seconds() / 3600, 1) if len(snapshots) > 1 else 0,
        "cpu": {
            "stats":  stats(cpu_vals),
            "trend":  trend(cpu_vals),
        },
        "ram": {
            "stats":  stats(ram_vals),
            "trend":  trend(ram_vals),
            "total_gb": round(snapshots[-1].ram_total_gb, 1) if snapshots[-1].ram_total_gb else None,
        },
        "temperature_cpu": {
            "stats":  stats(temp_vals),
            "trend":  trend(temp_vals),
        } if temp_vals else None,
        "gpu": {
            "name":   snapshots[-1].gpu_name or "—",
            "usage":  stats(gpu_vals),
            "temp":   stats(gpu_temps),
        } if gpu_vals else None,
        "disk_alerts": disk_alerts,
        "peaks":        peaks,
        "recent_alerts": [],  # se llena abajo
    }


def _get_recent_alerts(device):
    """Obtiene las alertas recientes del dispositivo."""
    from core.models import AlertEvent
    since = timezone.now() - timedelta(days=7)
    events = AlertEvent.objects.filter(
        device=device, fired_at__gte=since
    ).order_by("-fired_at")[:10]
    return [
        {
            "metric":   e.metric,
            "value":    e.value,
            "severity": e.severity,
            "time":     timezone.localtime(e.fired_at).strftime("%d/%m %H:%M"),
            "status":   e.status,
        }
        for e in events
    ]


def _build_prompt(summary: dict, alerts: list) -> str:
    summary["recent_alerts"] = alerts
    data_str = json.dumps(summary, ensure_ascii=False, indent=2)

    return f"""Eres el motor de análisis predictivo de Sentinel XO, una plataforma MSP de monitoreo de infraestructura TI.

Analiza los siguientes datos de telemetría del dispositivo y genera un análisis inteligente en español.

DATOS DE TELEMETRÍA:
{data_str}

Genera un análisis JSON con EXACTAMENTE esta estructura (sin markdown, solo JSON puro):
{{
  "estado_general": "ok|advertencia|critico",
  "resumen": "Una oración concisa del estado general del equipo (máximo 120 caracteres)",
  "insights": [
    {{
      "tipo": "patron|tendencia|riesgo|recomendacion|normal",
      "icono": "emoji apropiado",
      "titulo": "Título corto (máximo 50 caracteres)",
      "detalle": "Explicación clara y accionable (máximo 150 caracteres)",
      "severidad": "info|warning|critical"
    }}
  ],
  "prediccion": "Una predicción específica sobre el comportamiento futuro del equipo en las próximas 24-48 horas (máximo 200 caracteres)",
  "accion_prioritaria": "La acción más importante que debe tomar el técnico ahora mismo, o 'Sin acciones urgentes' si todo está bien (máximo 150 caracteres)"
}}

Reglas:
- Genera entre 3 y 6 insights relevantes
- Sé específico con números cuando los tengas
- Si hay tendencias preocupantes, indícalas claramente
- Si todo está bien, dilo con confianza
- Detecta patrones como calentamiento progresivo, uso excesivo de RAM, picos recurrentes
- Solo JSON, sin texto adicional"""


@login_required
@require_GET
def device_ai_analysis(request, device_id):
    """
    GET /api/v1/devices/<device_id>/ai-analysis/
    Genera análisis predictivo IA para un dispositivo.
    """
    from core.models import HardwareDevice, TelemetrySnapshot
    from django.conf import settings

    device = get_object_or_404(HardwareDevice, pk=device_id, is_active=True)

    if not request.user.is_staff:
        if not request.user.client_portals.filter(pk=device.client_id).exists():
            return JsonResponse({"error": "Sin acceso"}, status=403)

    # Obtener últimas 2 horas de snapshots (máx 500)
    since     = timezone.now() - timedelta(hours=2)
    snapshots = list(
        TelemetrySnapshot.objects.filter(
            device=device, captured_at__gte=since
        ).order_by("captured_at")[:500]
    )

    if len(snapshots) < 5:
        return JsonResponse({
            "error": "insufficient_data",
            "message": "Se necesitan al menos 5 minutos de datos para generar un análisis.",
        }, status=200)

    # Construir resumen y prompt
    summary = _build_telemetry_summary(device, snapshots)
    alerts  = _get_recent_alerts(device)
    prompt  = _build_prompt(summary, alerts)

    # Llamar a Claude API
    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    logger.info(f"ANTHROPIC_API_KEY presente: {bool(api_key)}, longitud: {len(api_key)}, prefijo: {api_key[:12]}...")

    try:
        payload = json.dumps({
            "model":      CLAUDE_MODEL,
            "max_tokens": 1000,
            "messages":   [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            CLAUDE_API_URL,
            data=payload,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("x-api-key", api_key)

        with urllib.request.urlopen(req, timeout=30) as resp:
            result  = json.loads(resp.read().decode())
            raw_txt = result["content"][0]["text"].strip()

            # Limpiar posibles backticks
            if raw_txt.startswith("```"):
                raw_txt = raw_txt.split("```")[1]
                if raw_txt.startswith("json"):
                    raw_txt = raw_txt[4:]
            raw_txt = raw_txt.strip()

            analysis = json.loads(raw_txt)
            logger.info(f"AI analysis OK para {device.display_name}")

            return JsonResponse({
                "status":   "ok",
                "device":   device.display_name,
                "samples":  summary["samples"],
                "analysis": analysis,
            })

    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")[:300]
        logger.error(f"Claude API error {e.code}: {body}")
        return JsonResponse({
            "error":   "api_error",
            "message": f"Error de la API: HTTP {e.code}",
        }, status=200)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error en respuesta IA: {e}")
        return JsonResponse({
            "error":   "parse_error",
            "message": "Error procesando la respuesta de IA.",
        }, status=200)
    except Exception as e:
        logger.error(f"AI analysis error: {e}")
        return JsonResponse({
            "error":   "error",
            "message": str(e)[:200],
        }, status=200)


def diagnose_incident(incident) -> dict | None:
    """
    Genera diagnóstico automático de un incidente usando Claude.
    Analiza los snapshots de los últimos 30 minutos antes del incidente.
    Se llama en background al crear un incidente.
    """
    from core.models import TelemetrySnapshot
    from django.conf import settings

    # Obtener snapshots del dispositivo afectado (si tiene)
    device   = incident.device
    context  = {}

    if device:
        since = incident.created_at - timedelta(minutes=30)
        until = incident.created_at + timedelta(minutes=5)
        snapshots = list(
            TelemetrySnapshot.objects.filter(
                device=device,
                captured_at__gte=since,
                captured_at__lte=until,
            ).order_by("captured_at")[:200]
        )
        if snapshots:
            context = _build_telemetry_summary(device, snapshots)

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")

    prompt = f"""Eres el motor de diagnóstico automático de {company}, plataforma MSP de monitoreo TI.

Se ha creado el siguiente incidente:
- Título: {incident.title}
- Severidad: {incident.get_severity_display()}
- Categoría: {incident.get_category_display()}
- Cliente: {incident.client.company_name}
- Dispositivo: {device.display_name if device else "No especificado"}
- Hora: {timezone.localtime(incident.created_at).strftime("%d/%m/%Y %H:%M:%S")}

{"Datos de telemetría del equipo (30 min antes del incidente):" if context else "Sin datos de telemetría disponibles."}
{json.dumps(context, ensure_ascii=False, indent=2) if context else ""}

Genera un diagnóstico JSON con EXACTAMENTE esta estructura (sin markdown, solo JSON puro):
{{
  "causa_probable": "Descripción clara de la causa más probable del incidente (máximo 200 caracteres)",
  "evidencias": [
    "Evidencia 1 basada en los datos (máximo 100 caracteres)",
    "Evidencia 2 (máximo 100 caracteres)"
  ],
  "pasos_resolucion": [
    "Paso 1 concreto y accionable",
    "Paso 2",
    "Paso 3"
  ],
  "tiempo_estimado": "Estimación del tiempo para resolver (ej: '15-30 minutos', '1-2 horas')",
  "prevencion": "Cómo evitar que este incidente se repita (máximo 150 caracteres)",
  "prioridad_real": "baja|media|alta|critica"
}}

Si no hay datos de telemetría, basa el diagnóstico en el título y categoría del incidente.
Solo JSON, sin texto adicional."""

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    logger.info(f"ANTHROPIC_API_KEY presente: {bool(api_key)}, longitud: {len(api_key)}")

    try:
        payload = json.dumps({
            "model":      CLAUDE_MODEL,
            "max_tokens": 800,
            "messages":   [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            CLAUDE_API_URL,
            data=payload,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("x-api-key", api_key)

        with urllib.request.urlopen(req, timeout=25) as resp:
            result  = json.loads(resp.read().decode())
            raw_txt = result["content"][0]["text"].strip()
            if raw_txt.startswith("```"):
                raw_txt = raw_txt.split("```")[1]
                if raw_txt.startswith("json"):
                    raw_txt = raw_txt[4:]
            raw_txt = raw_txt.strip()
            diagnosis = json.loads(raw_txt)
            logger.info(f"Diagnóstico IA generado para incidente #{incident.pk}: {incident.title[:50]}")
            return diagnosis

    except Exception as e:
        logger.error(f"Error generando diagnóstico IA para incidente #{incident.pk}: {e}")
        return None


@login_required
@require_GET
def incident_ai_diagnosis(request, incident_id):
    """
    GET /api/v1/incidents/<id>/diagnosis/
    Genera o regenera el diagnóstico IA de un incidente existente.
    """
    from core.models import MaintenanceIncident
    incident = get_object_or_404(MaintenanceIncident, pk=incident_id)

    if not request.user.is_staff:
        if not request.user.client_portals.filter(pk=incident.client_id).exists():
            return JsonResponse({"error": "Sin acceso"}, status=403)

    # Si ya tiene diagnóstico y no se pide regenerar, devolver el existente
    force = request.GET.get("force", "false") == "true"
    if incident.ai_diagnosis and not force:
        return JsonResponse({"status": "ok", "diagnosis": incident.ai_diagnosis, "cached": True})

    diagnosis = diagnose_incident(incident)
    if diagnosis:
        incident.ai_diagnosis = diagnosis
        incident.save(update_fields=["ai_diagnosis"])
        return JsonResponse({"status": "ok", "diagnosis": diagnosis, "cached": False})

    return JsonResponse({"error": "No se pudo generar el diagnóstico"}, status=200)


def generate_narrative_summary(client, year: int, month: int, summary: dict) -> str | None:
    """
    Genera un resumen ejecutivo narrativo en español para el reporte mensual PDF.
    Cuenta la historia del mes: cómo operó la infraestructura, qué pasó y qué sigue.
    Retorna texto plano (2-3 párrafos) o None si falla.
    """
    from core.models import AlertEvent, TelemetrySnapshot
    from django.conf import settings
    from dateutil.relativedelta import relativedelta

    period_start = timezone.make_aware(datetime(year, month, 1))
    period_end   = period_start + relativedelta(months=1)
    month_name   = {
        1:"enero",2:"febrero",3:"marzo",4:"abril",5:"mayo",6:"junio",
        7:"julio",8:"agosto",9:"septiembre",10:"octubre",11:"noviembre",12:"diciembre"
    }.get(month, str(month))

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")

    # ── Incidentes resueltos del período ──────────────────────────────────────
    incidents = list(client.incidents.filter(
        resolved_at__range=(period_start, period_end), is_resolved=True
    ).values("title", "severity", "category")[:15])

    incidents_open = list(client.incidents.filter(
        is_resolved=False
    ).values("title", "severity")[:10])

    # ── Alertas disparadas en el período, agrupadas por dispositivo/métrica ────
    alerts_qs = AlertEvent.objects.filter(
        device__client=client,
        fired_at__range=(period_start, period_end),
    ).select_related("device")[:30]

    alert_summary = {}
    for a in alerts_qs:
        key = (a.device.display_name, a.metric)
        if key not in alert_summary:
            alert_summary[key] = {"count": 0, "severity": a.severity, "max_value": a.value}
        alert_summary[key]["count"] += 1
        alert_summary[key]["max_value"] = max(alert_summary[key]["max_value"], a.value)

    alert_list = [
        {
            "dispositivo": k[0], "metrica": k[1],
            "veces": v["count"], "severidad": v["severity"], "valor_max": round(v["max_value"], 1)
        }
        for k, v in alert_summary.items()
    ]

    # ── Estado por dispositivo (resumen de telemetría del período) ─────────────
    devices_summary = []
    for dev in client.devices.filter(is_active=True):
        snaps = list(TelemetrySnapshot.objects.filter(
            device=dev, captured_at__range=(period_start, period_end)
        ).order_by("captured_at"))
        if not snaps:
            continue
        cpu_vals  = [s.cpu_percent for s in snaps if s.cpu_percent is not None]
        ram_vals  = [s.ram_used_percent for s in snaps if s.ram_used_percent is not None]
        temp_vals = [_extract_cpu_temp(s.temperatures or []) for s in snaps]
        temp_vals = [t for t in temp_vals if t is not None]

        devices_summary.append({
            "nombre":        dev.display_name,
            "cpu_promedio":  round(sum(cpu_vals)/len(cpu_vals), 1) if cpu_vals else None,
            "cpu_max":       round(max(cpu_vals), 1) if cpu_vals else None,
            "ram_promedio":  round(sum(ram_vals)/len(ram_vals), 1) if ram_vals else None,
            "temp_max":      round(max(temp_vals), 1) if temp_vals else None,
            "muestras":      len(snaps),
        })

    # ── Dominios y licencias ────────────────────────────────────────────────────
    domains_critical = list(client.domains.filter(
        status__in=["critical", "expired"]
    ).values("fqdn", "status")[:5])

    context = {
        "cliente":           client.company_name,
        "periodo":           f"{month_name} {year}",
        "uptime_promedio":   summary.get("avg_uptime_percent"),
        "equipos_total":     summary.get("devices_count"),
        "incidentes_resueltos": incidents,
        "incidentes_pendientes": incidents_open,
        "alertas_disparadas":   alert_list,
        "dispositivos":         devices_summary,
        "dominios_criticos":    domains_critical,
    }

    prompt = f"""Eres el redactor de informes ejecutivos de {company}, una plataforma MSP de monitoreo de infraestructura TI.

Genera el resumen ejecutivo narrativo para el reporte mensual de un cliente, basándote en estos datos:

{json.dumps(context, ensure_ascii=False, indent=2, default=str)}

INSTRUCCIONES:
- Escribe en español, tono profesional pero cercano, dirigido al cliente (no técnico)
- Escribe 2-3 párrafos cortos (máximo 600 caracteres en total)
- Párrafo 1: cómo operó la infraestructura durante el mes en general (uptime, estabilidad)
- Párrafo 2: menciona eventos relevantes (incidentes resueltos, alertas, patrones detectados) de forma natural, sin listas
- Párrafo 3 (opcional): qué se recomienda o qué viene, si hay pendientes o dominios críticos
- Si todo estuvo perfecto y sin incidentes, dilo con confianza y transmite tranquilidad
- NO uses markdown, NO uses listas, NO uses títulos — solo texto narrativo fluido
- NO repitas números exactos de forma robótica, intégralos naturalmente en las oraciones
- Responde SOLO con el texto del resumen, sin comillas ni explicaciones adicionales"""

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    logger.info(f"ANTHROPIC_API_KEY presente: {bool(api_key)}, longitud: {len(api_key)}")

    try:
        payload = json.dumps({
            "model":      CLAUDE_MODEL,
            "max_tokens": 500,
            "messages":   [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(
            CLAUDE_API_URL,
            data=payload,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("x-api-key", api_key)

        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
            text   = result["content"][0]["text"].strip()
            logger.info(f"Narrativa IA generada para {client.company_name} {month_name} {year}")
            return text

    except Exception as e:
        logger.error(f"Error generando narrativa IA para {client.company_name}: {e}")
        return None


def generate_security_analysis(client, security_check) -> dict | None:
    """
    Genera un análisis de postura de seguridad con IA, combinando:
      - Microsoft Secure Score
      - Cobertura de MFA
      - Estado de certificados SSL de los dominios del cliente
      - Patrones recientes de alertas

    Retorna un dict JSON con nivel de riesgo, hallazgos y recomendaciones,
    o None si falla.
    """
    from django.conf import settings

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")

    # ── Certificados SSL de los dominios del cliente ───────────────────────────
    domains_ssl = []
    for d in client.domains.all():
        domains_ssl.append({
            "dominio":          d.fqdn,
            "dias_venc_dominio": d.days_until_expiry,
            "ssl_estado":        d.ssl_status,
            "ssl_dias_venc":     d.days_until_ssl_expiry,
            "ssl_emisor":        d.ssl_issuer or None,
            "ssl_error":         d.ssl_error or None,
        })

    # ── Contexto de seguridad ────────────────────────────────────────────────
    context = {
        "cliente": client.company_name,
        "secure_score": {
            "actual": security_check.secure_score,
            "maximo": security_check.secure_score_max,
            "porcentaje": security_check.secure_score_percent,
        } if security_check.secure_score is not None else None,
        "mfa": {
            "registrados": security_check.mfa_registered,
            "total":       security_check.mfa_total,
            "porcentaje":  security_check.mfa_percent,
            "sin_mfa":     security_check.check_details.get("mfa", {}).get("no_mfa_users", []),
        } if security_check.mfa_total is not None else None,
        "dominios_ssl": domains_ssl,
        "notify_incidents_only": getattr(client, "notify_incidents_only", False),
    }

    prompt = f"""Eres el analista de ciberseguridad de {company}, una plataforma MSP de monitoreo de infraestructura TI.

Analiza la postura de seguridad del siguiente cliente y genera un reporte ejecutivo en español:

{json.dumps(context, ensure_ascii=False, indent=2, default=str)}

Genera un análisis JSON con EXACTAMENTE esta estructura (sin markdown, solo JSON puro):
{{
  "nivel_riesgo": "bajo|medio|alto|critico",
  "resumen": "Resumen ejecutivo de 1-2 oraciones sobre la postura general de seguridad (máximo 200 caracteres)",
  "hallazgos": [
    {{
      "titulo": "Título corto del hallazgo (máximo 60 caracteres)",
      "detalle": "Explicación clara del riesgo o fortaleza (máximo 150 caracteres)",
      "severidad": "info|warning|critical",
      "categoria": "identidad|certificados|configuracion|fortaleza"
    }}
  ],
  "recomendaciones": [
    {{
      "accion": "Acción concreta a tomar (máximo 120 caracteres)",
      "prioridad": "baja|media|alta|critica",
      "impacto": "Qué mejora esto (máximo 80 caracteres)"
    }}
  ]
}}

Reglas:
- Genera entre 2 y 5 hallazgos
- Genera entre 1 y 4 recomendaciones, ordenadas por prioridad
- Si el Secure Score es bajo (<50%), o la cobertura MFA es baja (<70%), o hay certificados SSL vencidos/críticos, el nivel_riesgo debe reflejarlo
- Si todo está en buen estado, dilo con confianza pero igual sugiere mejoras incrementales
- Sé específico citando los datos reales (porcentajes, nombres de dominios, usuarios sin MFA si los hay — sin exponer emails completos, usa solo el nombre de usuario antes del @)
- Solo JSON, sin texto adicional"""

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()

    try:
        payload = json.dumps({
            "model":      CLAUDE_MODEL,
            "max_tokens": 1000,
            "messages":   [{"role": "user", "content": prompt}],
        }).encode("utf-8")

        req = urllib.request.Request(CLAUDE_API_URL, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("x-api-key", api_key)

        with urllib.request.urlopen(req, timeout=30) as resp:
            result  = json.loads(resp.read().decode())
            raw_txt = result["content"][0]["text"].strip()
            if raw_txt.startswith("```"):
                raw_txt = raw_txt.split("```")[1]
                if raw_txt.startswith("json"):
                    raw_txt = raw_txt[4:]
            raw_txt = raw_txt.strip()
            analysis = json.loads(raw_txt)
            logger.info(f"Análisis de seguridad IA generado para {client.company_name}: "
                        f"riesgo={analysis.get('nivel_riesgo')}")
            return analysis

    except Exception as e:
        logger.error(f"Error generando análisis de seguridad IA para {client.company_name}: {e}")
        return None
