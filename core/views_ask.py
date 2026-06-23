"""
Sentinel XO — "Pregúntale a Sentinel"
=====================================
Asistente en lenguaje natural sobre la flota monitoreada.

Arquitectura segura (tool-calling acotado):
- Claude SOLO puede invocar las herramientas definidas aquí (consultas ORM
  predefinidas). Nunca ejecuta SQL ni código generado por el modelo.
- Cada herramienta filtra por los clientes que el usuario puede ver
  (staff = todos; usuario de portal = solo los suyos), respetando multi-tenant.
- Claude razona y redacta la respuesta, pero los datos provienen siempre de
  consultas reales.
"""
import json
import os
import logging
import urllib.request
import urllib.error
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from core.models import (
    Client, HardwareDevice, NetworkSnapshot, SoftwareSnapshot,
    SecurityAnomalyEvent, SecurityCheck, Domain, MaintenanceIncident,
)
from .views_ai import _extract_cpu_temp  # reutiliza extractor de temperatura CPU

logger = logging.getLogger("sentinel.ai")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-6"

MAX_TOOL_ROUNDS = 5
MAX_RESULT_ROWS = 60


# ── Permisos ────────────────────────────────────────────────────────────────

def _allowed_clients(user):
    """Clientes que el usuario puede consultar."""
    qs = Client.objects.filter(is_active=True)
    if user.is_staff:
        return qs
    return qs.filter(portal_users=user)


def _local(dt):
    return timezone.localtime(dt).strftime("%d/%m %H:%M") if dt else None


# ── Herramientas (consultas ORM acotadas) ───────────────────────────────────
# Cada función recibe (user, **kwargs) y devuelve datos JSON-serializables.

def tool_list_clients(user, **kw):
    out = []
    for c in _allowed_clients(user).prefetch_related("devices"):
        devs = [d for d in c.devices.all() if d.is_active]
        offline = sum(1 for d in devs if not d.is_online)
        out.append({
            "cliente": c.company_name,
            "plan": c.plan,
            "equipos": len(devs),
            "offline": offline,
            "salud": c.get_health_status(),
        })
    return out


def tool_device_search(user, **kw):
    client = (kw.get("client") or "").strip()
    status = kw.get("status")
    dtype  = kw.get("device_type")
    os_q   = (kw.get("os_contains") or "").strip()

    devs = (HardwareDevice.objects
            .filter(client__in=_allowed_clients(user), is_active=True)
            .select_related("client"))
    if client:
        devs = devs.filter(client__company_name__icontains=client)
    if dtype:
        devs = devs.filter(device_type=dtype)
    if os_q:
        devs = devs.filter(os__icontains=os_q)

    out = []
    for d in devs[:200]:
        online = d.is_online
        if status == "online" and not online:
            continue
        if status == "offline" and online:
            continue
        out.append({
            "equipo": d.display_name,
            "cliente": d.client.company_name,
            "tipo": d.get_device_type_display(),
            "estado": "en línea" if online else "offline",
            "os": d.os or "—",
            "ultimo_contacto": _local(d.last_seen),
        })
        if len(out) >= MAX_RESULT_ROWS:
            break
    return out


def tool_devices_by_resource(user, **kw):
    metric = kw.get("metric")
    try:
        threshold = float(kw.get("threshold", 0))
    except (TypeError, ValueError):
        threshold = 0.0
    client = (kw.get("client") or "").strip()

    devs = (HardwareDevice.objects
            .filter(client__in=_allowed_clients(user), is_active=True)
            .select_related("client"))
    if client:
        devs = devs.filter(client__company_name__icontains=client)

    out = []
    for d in devs:
        snap = d.snapshots.first()
        if not snap:
            continue
        if metric == "cpu":
            val = snap.cpu_percent
        elif metric == "ram":
            val = snap.ram_used_percent
        elif metric == "cpu_temp":
            val = _extract_cpu_temp(snap.temperatures or [])
        elif metric == "disk":
            ds = [x.get("used_percent", 0) for x in (snap.disk_usage or [])]
            val = max(ds) if ds else None
        else:
            val = None
        if val is not None and val >= threshold:
            out.append({
                "equipo": d.display_name,
                "cliente": d.client.company_name,
                "metric": metric,
                "valor": round(val, 1),
                "captado": _local(snap.captured_at),
            })
    out.sort(key=lambda r: r["valor"], reverse=True)
    return out[:MAX_RESULT_ROWS]


def tool_network_posture(user, **kw):
    flt = kw.get("filter")  # open_wifi | firewall_off | risk_critical | risk_warning
    client = (kw.get("client") or "").strip()

    snaps = (NetworkSnapshot.objects
             .filter(device__client__in=_allowed_clients(user), device__is_active=True)
             .select_related("device", "device__client"))
    if client:
        snaps = snaps.filter(device__client__company_name__icontains=client)

    out = []
    for n in snaps:
        if flt == "open_wifi":
            match = n.is_open_wifi
        elif flt == "firewall_off":
            match = (n.firewall_all_on is False)
        elif flt == "risk_critical":
            match = (n.risk_level == "critical")
        elif flt == "risk_warning":
            match = (n.risk_level == "warning")
        else:
            match = n.risk_level in ("critical", "warning")
        if not match:
            continue
        out.append({
            "equipo": n.device.display_name,
            "cliente": n.device.client.company_name,
            "riesgo": n.get_risk_level_display(),
            "wifi": n.wifi_ssid or "—",
            "cifrado": n.wifi_encryption or "—",
            "firewall_ok": n.firewall_all_on,
            "motivos": (n.risk_reasons or [])[:3],
        })
        if len(out) >= MAX_RESULT_ROWS:
            break
    return out


def tool_cve_findings(user, **kw):
    severity = kw.get("severity")  # critical | warning | info
    client = (kw.get("client") or "").strip()

    snaps = (SoftwareSnapshot.objects
             .filter(device__client__in=_allowed_clients(user),
                     cve_analysis__isnull=False)
             .select_related("device", "device__client"))
    if client:
        snaps = snaps.filter(device__client__company_name__icontains=client)

    out = []
    for s in snaps:
        a = s.cve_analysis or {}
        for h in a.get("hallazgos", []):
            if severity and h.get("severidad") != severity:
                continue
            out.append({
                "equipo": s.device.display_name,
                "cliente": s.device.client.company_name,
                "software": h.get("software"),
                "severidad": h.get("severidad"),
                "detalle": h.get("detalle"),
                "cves": h.get("cves_referencia", ""),
            })
            if len(out) >= MAX_RESULT_ROWS:
                return out
    return out


def tool_security_anomalies(user, **kw):
    status   = kw.get("status", "open")   # open | acknowledged
    severity = kw.get("severity")
    client   = (kw.get("client") or "").strip()

    qs = (SecurityAnomalyEvent.objects
          .filter(device__client__in=_allowed_clients(user))
          .select_related("device", "device__client"))
    if status:
        qs = qs.filter(status=status)
    if severity:
        qs = qs.filter(severity=severity)
    if client:
        qs = qs.filter(device__client__company_name__icontains=client)

    return [{
        "equipo": e.device.display_name,
        "cliente": e.device.client.company_name,
        "tipo": e.get_anomaly_type_display(),
        "severidad": e.severity,
        "estado": e.status,
        "detalle": e.detail_summary,
        "detectada": _local(e.detected_at),
    } for e in qs[:MAX_RESULT_ROWS]]


def tool_m365_security(user, **kw):
    client = (kw.get("client") or "").strip()
    clients = _allowed_clients(user)
    if client:
        clients = clients.filter(company_name__icontains=client)

    out = []
    for c in clients:
        sc = c.security_checks.first()  # ordenado por -checked_at
        signins = c.signin_anomalies.filter(status="open").count()
        out.append({
            "cliente": c.company_name,
            "secure_score_pct": sc.secure_score_percent if sc else None,
            "mfa_pct": sc.mfa_percent if sc else None,
            "verificado": _local(sc.checked_at) if sc else None,
            "anomalias_signin_abiertas": signins,
        })
    return out


def tool_domains_expiring(user, **kw):
    try:
        within = int(kw.get("within_days", 60))
    except (TypeError, ValueError):
        within = 60
    client = (kw.get("client") or "").strip()
    ssl    = bool(kw.get("ssl", False))

    qs = (Domain.objects
          .filter(client__in=_allowed_clients(user))
          .select_related("client"))
    if client:
        qs = qs.filter(client__company_name__icontains=client)

    out = []
    for d in qs:
        days = d.days_until_ssl_expiry if ssl else d.days_until_expiry
        if days is not None and days <= within:
            out.append({
                "dominio": d.fqdn,
                "cliente": d.client.company_name,
                "tipo": "SSL" if ssl else "dominio",
                "dias_restantes": days,
                "estado": d.ssl_status if ssl else d.status,
            })
    out.sort(key=lambda r: r["dias_restantes"])
    return out[:MAX_RESULT_ROWS]


def tool_incidents(user, **kw):
    status   = kw.get("status", "open")  # open | resolved | all
    client   = (kw.get("client") or "").strip()
    severity = kw.get("severity")

    qs = (MaintenanceIncident.objects
          .filter(client__in=_allowed_clients(user))
          .select_related("client", "device"))
    if status == "open":
        qs = qs.filter(is_resolved=False)
    elif status == "resolved":
        qs = qs.filter(is_resolved=True)
    if client:
        qs = qs.filter(client__company_name__icontains=client)
    if severity:
        qs = qs.filter(severity=severity)

    return [{
        "titulo": i.title,
        "cliente": i.client.company_name,
        "equipo": i.device.display_name if i.device else None,
        "categoria": i.get_category_display(),
        "severidad": i.get_severity_display(),
        "resuelto": i.is_resolved,
        "creado": _local(i.created_at),
    } for i in qs[:MAX_RESULT_ROWS]]


def tool_device_detail(user, **kw):
    name   = (kw.get("device_name") or "").strip()
    client = (kw.get("client") or "").strip()
    if not name:
        return {"error": "Falta el nombre del equipo."}

    devs = (HardwareDevice.objects
            .filter(client__in=_allowed_clients(user), is_active=True)
            .filter(Q(hostname__icontains=name) | Q(friendly_name__icontains=name))
            .select_related("client"))
    if client:
        devs = devs.filter(client__company_name__icontains=client)
    d = devs.first()
    if not d:
        return {"error": f"No se encontró un equipo que coincida con '{name}'."}

    snap = d.snapshots.first()
    net  = getattr(d, "network_snapshot", None)
    sw   = getattr(d, "software_snapshot", None)
    anomalies = d.security_anomalies.filter(status="open").count()
    incidents = d.incidents.filter(is_resolved=False).count()

    detail = {
        "equipo": d.display_name,
        "cliente": d.client.company_name,
        "tipo": d.get_device_type_display(),
        "os": d.os or "—",
        "estado": "en línea" if d.is_online else "offline",
        "ultimo_contacto": _local(d.last_seen),
        "anomalias_seguridad_abiertas": anomalies,
        "incidentes_abiertos": incidents,
    }
    if snap:
        disks = [{"mount": x.get("mountpoint"), "uso_pct": x.get("used_percent")}
                 for x in (snap.disk_usage or [])]
        detail["telemetria"] = {
            "cpu_pct": round(snap.cpu_percent, 1) if snap.cpu_percent is not None else None,
            "ram_pct": round(snap.ram_used_percent, 1) if snap.ram_used_percent is not None else None,
            "temp_cpu": _extract_cpu_temp(snap.temperatures or []),
            "discos": disks,
            "captado": _local(snap.captured_at),
        }
    if net:
        detail["red"] = {
            "riesgo": net.get_risk_level_display(),
            "wifi": net.wifi_ssid or "—",
            "cifrado": net.wifi_encryption or "—",
            "firewall_ok": net.firewall_all_on,
            "latencia_ms": net.latency_ms,
        }
    if sw:
        detail["software"] = {
            "programas": len(sw.software_list or []),
            "cve_riesgo": (sw.cve_analysis or {}).get("nivel_riesgo") if sw.cve_analysis else None,
        }
    return detail


TOOL_FUNCS = {
    "list_clients":        tool_list_clients,
    "device_search":       tool_device_search,
    "devices_by_resource": tool_devices_by_resource,
    "network_posture":     tool_network_posture,
    "cve_findings":        tool_cve_findings,
    "security_anomalies":  tool_security_anomalies,
    "m365_security":       tool_m365_security,
    "domains_expiring":    tool_domains_expiring,
    "incidents":           tool_incidents,
    "device_detail":       tool_device_detail,
}


# ── Esquemas de herramientas para la API ────────────────────────────────────

TOOLS_SCHEMA = [
    {
        "name": "list_clients",
        "description": "Lista los clientes monitoreados con su número de equipos, equipos offline y estado de salud general. Úsala para preguntas generales sobre clientes o panorama de la flota.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "device_search",
        "description": "Busca equipos por cliente, estado (online/offline), tipo o sistema operativo. Úsala para 'qué equipos están offline', 'servidores de X', 'equipos con Windows', etc.",
        "input_schema": {"type": "object", "properties": {
            "client": {"type": "string", "description": "Nombre (o parte) del cliente"},
            "status": {"type": "string", "enum": ["online", "offline"]},
            "device_type": {"type": "string", "enum": ["workstation", "server", "laptop", "printer", "network", "other"]},
            "os_contains": {"type": "string", "description": "Texto a buscar en el SO"},
        }},
    },
    {
        "name": "devices_by_resource",
        "description": "Equipos cuya última lectura supera un umbral en una métrica de recursos. Úsala para 'equipos con CPU/RAM/disco alto' o 'equipos calientes'.",
        "input_schema": {"type": "object", "properties": {
            "metric": {"type": "string", "enum": ["cpu", "ram", "disk", "cpu_temp"]},
            "threshold": {"type": "number", "description": "Umbral (% para cpu/ram/disk, °C para cpu_temp)"},
            "client": {"type": "string"},
        }, "required": ["metric", "threshold"]},
    },
    {
        "name": "network_posture",
        "description": "Equipos según postura de red insegura: WiFi abierta, firewall apagado, o nivel de riesgo de red. Úsala para 'equipos con firewall apagado', 'redes WiFi abiertas', 'riesgo de red crítico'.",
        "input_schema": {"type": "object", "properties": {
            "filter": {"type": "string", "enum": ["open_wifi", "firewall_off", "risk_critical", "risk_warning"]},
            "client": {"type": "string"},
        }},
    },
    {
        "name": "cve_findings",
        "description": "Hallazgos de vulnerabilidades (CVE) en el software instalado de los equipos. Úsala para 'equipos con vulnerabilidades', 'software crítico sin parchar'.",
        "input_schema": {"type": "object", "properties": {
            "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
            "client": {"type": "string"},
        }},
    },
    {
        "name": "security_anomalies",
        "description": "Anomalías de seguridad detectadas en equipos (nuevo admin local, firewall apagado, WiFi abierta, cambios DNS, etc.). Úsala para 'anomalías de seguridad abiertas'.",
        "input_schema": {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["open", "acknowledged"]},
            "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
            "client": {"type": "string"},
        }},
    },
    {
        "name": "m365_security",
        "description": "Postura de seguridad Microsoft 365 por cliente: Secure Score, cobertura de MFA y anomalías de inicio de sesión. Úsala para 'cobertura MFA', 'secure score', 'estado M365'.",
        "input_schema": {"type": "object", "properties": {
            "client": {"type": "string"},
        }},
    },
    {
        "name": "domains_expiring",
        "description": "Dominios o certificados SSL que vencen dentro de N días. Úsala para 'dominios por vencer', 'certificados SSL próximos a expirar'.",
        "input_schema": {"type": "object", "properties": {
            "within_days": {"type": "integer", "description": "Ventana en días (por defecto 60)"},
            "ssl": {"type": "boolean", "description": "true para vencimiento de SSL, false para vencimiento del dominio"},
            "client": {"type": "string"},
        }},
    },
    {
        "name": "incidents",
        "description": "Incidentes de mantenimiento por cliente/severidad/estado. Úsala para 'incidentes abiertos', 'incidentes críticos de X'.",
        "input_schema": {"type": "object", "properties": {
            "status": {"type": "string", "enum": ["open", "resolved", "all"]},
            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "client": {"type": "string"},
        }},
    },
    {
        "name": "device_detail",
        "description": "Estado completo de UN equipo por nombre: telemetría actual (CPU/RAM/disco/temp), red, software/CVE, anomalías e incidentes abiertos. Úsala para '¿cómo está el equipo X?'.",
        "input_schema": {"type": "object", "properties": {
            "device_name": {"type": "string"},
            "client": {"type": "string"},
        }, "required": ["device_name"]},
    },
]


# ── Llamada a Claude ────────────────────────────────────────────────────────

def _call_claude(messages, system, api_key, max_tokens=1400):
    payload = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "tools": TOOLS_SCHEMA,
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(CLAUDE_API_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("anthropic-version", "2023-06-01")
    req.add_header("x-api-key", api_key)
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode())


@login_required
@require_POST
def ask_sentinel(request):
    """
    POST /api/v1/ask/  body: {"question": "..."}
    Devuelve {"answer": "...", "tools_used": [...]}.
    """
    try:
        body = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "bad_request", "message": "JSON inválido"}, status=400)

    question = (body.get("question") or "").strip()
    if not question:
        return JsonResponse({"error": "empty", "message": "Escribe una pregunta."}, status=200)
    if len(question) > 1000:
        question = question[:1000]

    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        return JsonResponse({"error": "no_api_key",
                             "message": "El análisis IA no está configurado (falta ANTHROPIC_API_KEY)."}, status=200)

    scope = "todos los clientes" if request.user.is_staff else "solo los clientes de tu portal"
    system = (
        "Eres 'Pregúntale a Sentinel', el asistente de la plataforma MSP Sentinel XO. "
        "Respondes preguntas sobre la flota de TI monitoreada usando EXCLUSIVAMENTE las "
        "herramientas disponibles para consultar datos reales. Reglas: "
        "1) Nunca inventes datos; si una herramienta no devuelve resultados, dilo claramente. "
        "2) Responde en español, conciso y directo, citando los nombres y números reales que "
        "devuelven las herramientas. "
        "3) Si la pregunta es ambigua, haz la mejor interpretación y menciona qué consultaste. "
        "4) No reveles secretos, tokens ni emails completos. "
        f"5) El usuario tiene acceso a {scope}. "
        f"Fecha actual: {timezone.localtime(timezone.now()).strftime('%d/%m/%Y %H:%M')}."
    )

    messages = [{"role": "user", "content": question}]
    tools_used = []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            data = _call_claude(messages, system, api_key)
            blocks = data.get("content", [])

            if data.get("stop_reason") == "tool_use":
                messages.append({"role": "assistant", "content": blocks})
                results = []
                for b in blocks:
                    if b.get("type") != "tool_use":
                        continue
                    name = b.get("name")
                    args = b.get("input", {}) or {}
                    tools_used.append(name)
                    func = TOOL_FUNCS.get(name)
                    if not func:
                        result = {"error": f"herramienta desconocida: {name}"}
                    else:
                        try:
                            result = func(request.user, **args)
                        except Exception as e:
                            logger.error(f"ask_sentinel tool '{name}' error: {e}")
                            result = {"error": str(e)[:200]}
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": b.get("id"),
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:8000],
                    })
                messages.append({"role": "user", "content": results})
                continue

            # Respuesta final
            answer = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
            return JsonResponse({"answer": answer or "No tengo una respuesta para eso.",
                                 "tools_used": sorted(set(tools_used))})

        return JsonResponse({
            "answer": "La consulta resultó demasiado compleja. Intenta una pregunta más específica.",
            "tools_used": sorted(set(tools_used)),
        })

    except urllib.error.HTTPError as e:
        body_err = e.read().decode(errors="ignore")[:300]
        logger.error(f"ask_sentinel HTTP {e.code}: {body_err}")
        return JsonResponse({"error": "api_error",
                             "message": f"Error del servicio IA (HTTP {e.code})."}, status=200)
    except Exception as e:
        logger.error(f"ask_sentinel error: {e}")
        return JsonResponse({"error": "error", "message": str(e)[:200]}, status=200)
