"""
Sentinel XO — Digest IA semanal de la flota
===========================================
Genera y envía por email un resumen ejecutivo semanal:

  • Por cliente : cada cliente activo recibe su propio resumen (solo sus equipos),
                  a los destinatarios de Client.get_alert_recipients().
  • Interno     : un digest global de TODA la flota al equipo Perseus.

Claude redacta el resumen ejecutivo (mismo patrón urllib + x-api-key que el
resto de la IA del proyecto). El email se renderiza aquí en HTML (Resend soporta
HTML; el _resend_send del proyecto es solo texto, así que este módulo trae su
propio sender HTML sin tocar el pipeline existente).
"""
import os
import json
import html
import logging
import urllib.request
import urllib.error
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from core.models import (
    Client, SecurityAnomalyEvent, SoftwareSnapshot,
)
from core.security_score import snapshot_security_score

logger = logging.getLogger("perseus")

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL   = "claude-sonnet-4-6"

BRAND = "#2f7bff"
CYAN  = "#22e6ff"
INK   = "#0b1220"


# ── Envío de email HTML vía Resend ──────────────────────────────────────────

def _send_html_email(subject: str, html_body: str, to: list) -> bool:
    api_key      = getattr(settings, "RESEND_API_KEY", "")
    sender_email = getattr(settings, "DEFAULT_FROM_EMAIL", "soporte@perseustechnology.dev")
    sender_name  = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    if not api_key:
        logger.error("digest: RESEND_API_KEY no configurada")
        return False
    if not to:
        return False

    payload = json.dumps({
        "from":    f"{sender_name} <{sender_email}>",
        "to":      to,
        "subject": subject,
        "html":    html_body,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
                "User-Agent":    "SentinelXO/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            json.loads(resp.read().decode())
        logger.info(f"digest enviado → {', '.join(to)}")
        _log_email(to, subject, "sent", "")
        return True
    except urllib.error.HTTPError as e:
        err = f"HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}"
        logger.error(f"digest email error: {err}")
        _log_email(to, subject, "failed", err)
        return False
    except Exception as e:
        logger.error(f"digest email error: {e}")
        _log_email(to, subject, "failed", str(e)[:200])
        return False


def _log_email(to, subject, status, err):
    """Registra el envío en EmailLog si el modelo está disponible."""
    try:
        from emailmon.models import EmailLog
        for r in to:
            EmailLog.objects.create(
                recipient=r, subject=subject, category="other",
                status=status, error_msg=err,
            )
    except Exception:
        pass


# ── Llamada a Claude ────────────────────────────────────────────────────────

def _claude_json(prompt: str, max_tokens: int = 900) -> dict | None:
    api_key = (getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "")).strip()
    if not api_key:
        logger.error("digest: ANTHROPIC_API_KEY no configurada")
        return None
    try:
        payload = json.dumps({
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(CLAUDE_API_URL, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("anthropic-version", "2023-06-01")
        req.add_header("x-api-key", api_key)
        with urllib.request.urlopen(req, timeout=40) as resp:
            result = json.loads(resp.read().decode())
        raw = result["content"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except Exception as e:
        logger.error(f"digest Claude error: {e}")
        return None


# ── Agregación de datos por cliente ─────────────────────────────────────────

def build_client_digest(client) -> dict:
    devices = list(client.devices.filter(is_active=True))
    total   = len(devices)
    offline = [d.display_name for d in devices if not d.is_online]

    high = []
    for d in devices:
        snap = d.snapshots.first()
        if not snap:
            continue
        disk_max = max([x.get("used_percent", 0) for x in (snap.disk_usage or [])], default=0)
        if snap.cpu_percent and snap.cpu_percent > 90:
            high.append(f"{d.display_name}: CPU {snap.cpu_percent:.0f}%")
        if snap.ram_used_percent and snap.ram_used_percent > 90:
            high.append(f"{d.display_name}: RAM {snap.ram_used_percent:.0f}%")
        if disk_max > 90:
            high.append(f"{d.display_name}: Disco {disk_max:.0f}%")

    anomalies   = SecurityAnomalyEvent.objects.filter(device__client=client, status="open")
    anomaly_cnt = anomalies.count()
    anomaly_crit = anomalies.filter(severity="critical").count()

    cve_risk = []
    for s in SoftwareSnapshot.objects.filter(device__client=client, cve_analysis__isnull=False).select_related("device"):
        nivel = (s.cve_analysis or {}).get("nivel_riesgo")
        if nivel in ("alto", "critico"):
            cve_risk.append(f"{s.device.display_name}: riesgo {nivel}")

    sc = client.security_checks.first()
    signin_open = client.signin_anomalies.filter(status="open").count()

    dom_exp = []
    for d in client.domains.all():
        if d.days_until_expiry is not None and d.days_until_expiry <= 30:
            dom_exp.append(f"{d.fqdn}: dominio vence en {d.days_until_expiry}d")
        if d.days_until_ssl_expiry is not None and d.days_until_ssl_expiry <= 30:
            dom_exp.append(f"{d.fqdn}: SSL vence en {d.days_until_ssl_expiry}d")

    incidents_open = client.incidents.filter(is_resolved=False).count()

    return {
        "cliente": client.company_name,
        "equipos_total": total,
        "equipos_offline": offline,
        "recursos_altos": high[:8],
        "anomalias_abiertas": anomaly_cnt,
        "anomalias_criticas": anomaly_crit,
        "cve_riesgo_alto": cve_risk[:8],
        "m365_secure_score_pct": sc.secure_score_percent if sc else None,
        "m365_mfa_pct": sc.mfa_percent if sc else None,
        "m365_signin_anomalias": signin_open,
        "dominios_ssl_por_vencer": dom_exp[:8],
        "incidentes_abiertos": incidents_open,
    }


def _summarize(data: dict, fleet: bool = False) -> dict:
    """Pide a Claude un resumen ejecutivo. Devuelve dict con estructura fija."""
    scope = ("toda la flota de varios clientes" if fleet
             else "un único cliente")
    prompt = f"""Eres el analista MSP de {getattr(settings, 'SENTINEL_COMPANY_NAME', 'Sentinel XO')}.
Genera un resumen ejecutivo SEMANAL en español para {scope}, a partir de estos datos agregados:

{json.dumps(data, ensure_ascii=False, indent=2)}

Devuelve SOLO JSON puro (sin markdown) con EXACTAMENTE esta estructura:
{{
  "estado_general": "ok|advertencia|critico",
  "resumen": "2 a 4 frases ejecutivas sobre el estado general de la semana (máximo 400 caracteres)",
  "destacados": ["punto relevante conciso", "..."],
  "acciones": ["acción recomendada concreta", "..."]
}}

Reglas:
- 'destacados': 2 a 5 puntos. Cita números/nombres reales de los datos.
- 'acciones': 0 a 4 recomendaciones priorizadas; si todo está sano, deja [].
- Si no hay equipos o datos, dilo con claridad.
- Tono profesional y directo. Solo JSON."""
    result = _claude_json(prompt)
    if not result:
        # Fallback sin IA: resumen mínimo a partir de los datos
        return {
            "estado_general": "advertencia" if (data.get("anomalias_abiertas") or data.get("equipos_offline")) else "ok",
            "resumen": "Resumen automático no disponible esta semana (servicio IA sin respuesta). "
                       "Revisa los indicadores adjuntos.",
            "destacados": [],
            "acciones": [],
        }
    return result


# ── Render HTML del email ───────────────────────────────────────────────────

_STATE = {
    "ok":          ("#10b981", "Estable"),
    "advertencia": ("#e0930b", "Requiere atención"),
    "critico":     ("#e5484d", "Crítico"),
}


def _esc(s):
    return html.escape(str(s)) if s is not None else ""


def _metric_cell(label, value, accent=BRAND):
    return f"""<td style="padding:8px 12px;background:#f6f8fc;border-radius:8px;">
      <div style="font-size:10px;color:#64748b;text-transform:uppercase;letter-spacing:.04em;">{_esc(label)}</div>
      <div style="font-size:20px;font-weight:700;color:{accent};font-family:Arial,sans-serif;">{_esc(value)}</div>
    </td>"""


def _list_block(title, items, color):
    if not items:
        return ""
    lis = "".join(
        f'<li style="margin-bottom:6px;font-size:13px;color:#334155;line-height:1.5;">{_esc(i)}</li>'
        for i in items
    )
    return f"""<div style="margin-top:18px;">
      <div style="font-size:11px;font-weight:700;color:{color};text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">{_esc(title)}</div>
      <ul style="margin:0;padding-left:18px;">{lis}</ul>
    </div>"""


def render_digest_html(title: str, period: str, summary: dict, data: dict,
                       extra_table: str = "") -> str:
    color, state_label = _STATE.get(summary.get("estado_general", "ok"), _STATE["ok"])
    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")

    # Métricas rápidas
    metrics = []
    if data.get("equipos_total") is not None:
        metrics.append(_metric_cell("Equipos", data["equipos_total"]))
    off = data.get("equipos_offline")
    if isinstance(off, list):
        metrics.append(_metric_cell("Offline", len(off), "#e5484d" if off else "#10b981"))
    if data.get("anomalias_abiertas") is not None:
        metrics.append(_metric_cell("Anomalías", data["anomalias_abiertas"],
                                    "#e5484d" if data["anomalias_abiertas"] else "#10b981"))
    if data.get("m365_secure_score_pct") is not None:
        metrics.append(_metric_cell("Secure Score", f"{data['m365_secure_score_pct']:.0f}%"))
    if data.get("m365_mfa_pct") is not None:
        metrics.append(_metric_cell("MFA", f"{data['m365_mfa_pct']:.0f}%"))

    metrics_row = ""
    if metrics:
        cells = '<td style="width:8px;"></td>'.join(metrics)
        metrics_row = f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;margin-top:16px;border-collapse:separate;"><tr>{cells}</tr></table>'

    destacados = _list_block("Puntos destacados", summary.get("destacados", []), BRAND)
    acciones   = _list_block("Acciones recomendadas", summary.get("acciones", []), "#e0930b")

    return f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
</head><body style="margin:0;padding:0;background:#eef2f8;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef2f8;padding:24px 12px;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:14px;overflow:hidden;box-shadow:0 8px 30px rgba(15,23,42,0.08);">

        <!-- Header -->
        <tr><td style="background:{INK};padding:22px 28px;">
          <div style="height:3px;width:100%;background:linear-gradient(90deg,{CYAN},#9b6bff);border-radius:2px;margin-bottom:14px;"></div>
          <div style="color:#ffffff;font-size:18px;font-weight:700;">{_esc(title)}</div>
          <div style="color:#94a3b8;font-size:12px;margin-top:3px;">{_esc(period)} · {_esc(company)}</div>
        </td></tr>

        <!-- Estado -->
        <tr><td style="padding:20px 28px 0;">
          <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:{color}14;border:1px solid {color}33;border-radius:10px;">
            <tr>
              <td style="padding:12px 14px;width:12px;"><div style="width:10px;height:10px;border-radius:50%;background:{color};"></div></td>
              <td style="padding:12px 0;font-size:14px;font-weight:600;color:#0f172a;">{_esc(summary.get('resumen',''))}</td>
              <td style="padding:12px 14px;text-align:right;white-space:nowrap;">
                <span style="font-size:11px;font-weight:700;color:{color};">{_esc(state_label)}</span>
              </td>
            </tr>
          </table>
          {metrics_row}
          {destacados}
          {acciones}
          {extra_table}
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:24px 28px;">
          <div style="border-top:1px solid #e2e8f0;padding-top:14px;font-size:11px;color:#94a3b8;line-height:1.5;">
            Generado automáticamente por <strong style="color:#475569;">{_esc(company)}</strong> ·
            Resumen semanal de monitoreo. Este correo es informativo; no es necesario responder.
          </div>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body></html>"""


# ── Orquestación ────────────────────────────────────────────────────────────

def _period_label():
    now = timezone.localtime(timezone.now())
    start = now - timedelta(days=7)
    return f"Semana del {start.strftime('%d/%m')} al {now.strftime('%d/%m/%Y')}"


def send_client_digest(client) -> bool:
    recipients = client.get_alert_recipients()
    if not recipients:
        logger.info(f"digest: {client.company_name} sin destinatarios, omitido")
        return False
    data    = build_client_digest(client)
    summary = _summarize(data, fleet=False)
    htmlb   = render_digest_html(
        title=f"Resumen Semanal — {client.company_name}",
        period=_period_label(),
        summary=summary,
        data=data,
    )
    subject = f"[{getattr(settings,'SENTINEL_COMPANY_NAME','Sentinel XO')}] Resumen semanal — {client.company_name}"
    return _send_html_email(subject, htmlb, recipients)


def send_internal_digest(clients) -> bool:
    rows = []
    fleet = {
        "clientes": len(clients),
        "equipos_total": 0,
        "equipos_offline": 0,
        "anomalias_abiertas": 0,
        "incidentes_abiertos": 0,
        "clientes_detalle": [],
    }
    for c in clients:
        d = build_client_digest(c)
        off = len(d["equipos_offline"])
        fleet["equipos_total"]      += d["equipos_total"]
        fleet["equipos_offline"]    += off
        fleet["anomalias_abiertas"] += d["anomalias_abiertas"]
        fleet["incidentes_abiertos"] += d["incidentes_abiertos"]
        fleet["clientes_detalle"].append({
            "cliente": d["cliente"], "equipos": d["equipos_total"],
            "offline": off, "anomalias": d["anomalias_abiertas"],
            "incidentes": d["incidentes_abiertos"],
        })
        color = "#e5484d" if (off or d["anomalias_criticas"]) else ("#e0930b" if d["anomalias_abiertas"] else "#10b981")
        rows.append(
            f'<tr><td style="padding:8px 10px;font-size:13px;color:#0f172a;border-bottom:1px solid #eef2f7;">'
            f'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{color};margin-right:8px;"></span>{_esc(d["cliente"])}</td>'
            f'<td style="padding:8px 10px;font-size:13px;color:#475569;text-align:center;border-bottom:1px solid #eef2f7;">{d["equipos_total"]}</td>'
            f'<td style="padding:8px 10px;font-size:13px;color:#475569;text-align:center;border-bottom:1px solid #eef2f7;">{off}</td>'
            f'<td style="padding:8px 10px;font-size:13px;color:#475569;text-align:center;border-bottom:1px solid #eef2f7;">{d["anomalias_abiertas"]}</td></tr>'
        )

    table = ""
    if rows:
        table = (
            '<div style="margin-top:18px;"><div style="font-size:11px;font-weight:700;color:#0b1220;'
            'text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px;">Detalle por cliente</div>'
            '<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;">'
            '<tr><th align="left" style="padding:6px 10px;font-size:10px;color:#94a3b8;text-transform:uppercase;">Cliente</th>'
            '<th style="padding:6px 10px;font-size:10px;color:#94a3b8;">Equipos</th>'
            '<th style="padding:6px 10px;font-size:10px;color:#94a3b8;">Offline</th>'
            '<th style="padding:6px 10px;font-size:10px;color:#94a3b8;">Anomalías</th></tr>'
            + "".join(rows) + "</table></div>"
        )

    summary = _summarize(fleet, fleet=True)
    htmlb = render_digest_html(
        title="Resumen Semanal de la Flota",
        period=_period_label(),
        summary=summary,
        data={"equipos_total": fleet["equipos_total"],
              "equipos_offline": [None] * fleet["equipos_offline"],
              "anomalias_abiertas": fleet["anomalias_abiertas"]},
        extra_table=table,
    )
    to = [getattr(settings, "SENTINEL_DIGEST_EMAIL", "") or getattr(settings, "SENTINEL_SUPPORT_EMAIL", "")]
    to = [t for t in to if t]
    subject = f"[{getattr(settings,'SENTINEL_COMPANY_NAME','Sentinel XO')}] Resumen semanal de la flota"
    return _send_html_email(subject, htmlb, to)


@shared_task(name="reports.weekly_fleet_digest")
def weekly_fleet_digest():
    """Tarea Celery semanal: digest por cliente + digest interno de la flota."""
    clients = list(Client.objects.filter(is_active=True))
    sent = 0
    for c in clients:
        try:
            snapshot_security_score(c)   # guarda el score de seguridad (tendencia)
        except Exception as e:
            logger.error(f"snapshot score {c.company_name} falló: {e}")
        try:
            if send_client_digest(c):
                sent += 1
        except Exception as e:
            logger.error(f"digest cliente {c.company_name} falló: {e}")
    try:
        send_internal_digest(clients)
    except Exception as e:
        logger.error(f"digest interno falló: {e}")
    logger.info(f"weekly_fleet_digest: {sent}/{len(clients)} digests de cliente enviados")
    return sent
