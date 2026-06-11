"""
Sentinel XO — Motor de Alertas Inteligentes
Evalúa reglas en cada snapshot de telemetría recibido.
También se usa para alertas SMTP desde emailmon.
"""
import logging
from core.models import AlertEvent
from django.utils import timezone
from core.models import MaintenanceIncident, AlertRule, AlertEvent
from django.conf import settings

logger = logging.getLogger("sentinel.alerts")

METRIC_LABELS = {
    "cpu":       "CPU",
    "ram":       "RAM",
    "gpu_usage": "GPU Uso",
    "gpu_mem":   "GPU Memoria",
    "cpu_temp":  "Temperatura CPU",
    "gpu_temp":  "Temperatura GPU",
}
METRIC_UNITS = {
    "cpu":       "%",
    "ram":       "%",
    "gpu_usage": "%",
    "gpu_mem":   "%",
    "cpu_temp":  "°C",
    "gpu_temp":  "°C",
}
SEVERITY_EMOJIS = {"warning": "⚠️", "critical": "🔴"}

def _extract_cpu_temp(temperatures: list) -> float | None:
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

def _get_snapshot_value(snapshot, metric: str) -> float | None:
    if metric == "cpu":
        return snapshot.cpu_percent
    elif metric == "ram":
        return snapshot.ram_used_percent
    elif metric == "gpu_usage":
        return snapshot.gpu_usage_percent
    elif metric == "gpu_mem":
        return snapshot.gpu_memory_used_percent
    elif metric == "cpu_temp":
        return _extract_cpu_temp(snapshot.temperatures or [])
    elif metric == "gpu_temp":
        return snapshot.gpu_temp_celsius
    return None

def _is_in_cooldown(rule, device) -> bool:
    cutoff = timezone.now() - timezone.timedelta(minutes=rule.cooldown_minutes)
    return AlertEvent.objects.filter(
        rule=rule,
        device=device,
        fired_at__gte=cutoff,
        status="firing",
    ).exists()

def _build_alert_message(device, metric: str, value: float, threshold: float) -> str:
    label = METRIC_LABELS.get(metric, metric)
    unit  = METRIC_UNITS.get(metric, "")
    return (
        f"{device.display_name} — {label} en {value:.1f}{unit} "
        f"(umbral: {threshold:.0f}{unit})"
    )

def _send_alert_email(event) -> bool:
    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    client    = event.device.client
    label     = METRIC_LABELS.get(event.metric, event.metric)
    unit      = METRIC_UNITS.get(event.metric, "")
    emoji     = SEVERITY_EMOJIS.get(event.severity, "⚠️")
    sev_label = "Advertencia" if event.severity == "warning" else "Crítica"

    if getattr(client, "notify_incidents_only", False):
        logger.info(f"Alerta automática omitida para {client} (notify_incidents_only=True)")
        return False

    recipients = client.get_alert_recipients()
    if not recipients:
        return False

    subject = (
        f"{emoji} [{company}] Alerta {sev_label}: "
        f"{event.device.display_name} — {label} al {event.value:.1f}{unit}"
    )

    body = f"""Estimado equipo de {client.company_name},

El sistema de monitoreo Sentinel XO ha detectado una condición de alerta.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ALERTA {sev_label.upper()} DETECTADA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Equipo:     {event.device.display_name}
  Sistema:    {event.device.os or '—'}
  Métrica:    {label}
  Valor:      {event.value:.1f}{unit}
  Umbral:     {event.threshold:.0f}{unit}
  Severidad:  {sev_label}
  Hora:       {event.fired_at.strftime('%d/%m/%Y a las %H:%M:%S')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Se recomienda revisar el equipo a la brevedad.
Esta alerta se registra automáticamente como incidente en el sistema.

Ante cualquier consulta, contáctenos en {support}.

Saludos,
{company}
"""

    try:
        from emailmon.services import send_tracked_email
        return send_tracked_email(
            subject=subject,
            body=body,
            to=recipients,
            category="incident",
            client=client,
        )
    except Exception:
        try:
            from django.core.mail import send_mail
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                      recipients, fail_silently=True)
            return True
        except Exception as e:
            logger.error(f"Error enviando alerta por email: {e}")
            return False

def _create_incident_from_alert(event):
    label = METRIC_LABELS.get(event.metric, event.metric)
    unit  = METRIC_UNITS.get(event.metric, "")
    sev   = "critical" if event.severity == "critical" else "high"

    MaintenanceIncident.objects.create(
        client=event.device.client,
        device=event.device,
        title=f"Alerta automática: {label} al {event.value:.1f}{unit} en {event.device.display_name}",
        severity=sev,
        category="hardware",
        notify_email=False,  # ya se notificó desde el motor de alertas
        description=(
            f"Alerta disparada automáticamente por el motor de alertas Sentinel XO.\n"
            f"Métrica: {label}\n"
            f"Valor detectado: {event.value:.1f}{unit}\n"
            f"Umbral configurado: {event.threshold:.0f}{unit}\n"
            f"Hora: {event.fired_at.strftime('%d/%m/%Y %H:%M:%S')}"
        ),
    )

def evaluate_snapshot(snapshot) -> list:
    device  = snapshot.device
    client  = device.client
    fired   = []

    rules = AlertRule.objects.filter(
        client=client,
        is_active=True,
    ).filter(
        models_Q(device=device) | models_Q(device__isnull=True)
    )

    for rule in rules:
        value = _get_snapshot_value(snapshot, rule.metric)
        if value is None:
            continue  

        if value <= rule.threshold:
            continue  

        if _is_in_cooldown(rule, device):
            logger.debug(f"Alerta en cooldown: {rule} para {device}")
            continue

        message = _build_alert_message(device, rule.metric, value, rule.threshold)
        logger.warning(f"🔔 ALERTA [{rule.severity.upper()}]: {message}")

        event = AlertEvent.objects.create(
            rule=rule,
            device=device,
            metric=rule.metric,
            value=value,
            threshold=rule.threshold,
            severity=rule.severity,
            message=message,
            status="firing",
        )

        try:
            _create_incident_from_alert(event)
        except Exception as e:
            logger.error(f"Error creando incidente desde alerta: {e}")

        if rule.notify_email:
            try:
                notified = _send_alert_email(event)
                event.notified = notified
                event.save(update_fields=["notified"])
            except Exception as e:
                logger.error(f"Error enviando email de alerta: {e}")

        fired.append(event)

    return fired

def evaluate_smtp_failure(client, smtp_host: str, error_msg: str) -> None:
    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev")

    cutoff = timezone.now() - timezone.timedelta(minutes=60)
    recent = AlertEvent.objects.filter(
        device__client=client,
        metric="smtp",
        fired_at__gte=cutoff,
        status="firing",
    ).exists()
    if recent:
        return

    if getattr(client, "notify_incidents_only", False):
        return

    recipients = client.get_alert_recipients()
    if not recipients:
        return

    subject = f"🔴 [{company}] Alerta: Problema SMTP detectado — {client.company_name}"
    body = f"""Estimado equipo de {client.company_name},

El sistema de monitoreo Sentinel XO ha detectado un problema con el servidor de correo.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ALERTA SMTP DETECTADA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Servidor:   {smtp_host}
  Error:      {error_msg[:200]}
  Hora:       {timezone.now().strftime('%d/%m/%Y a las %H:%M:%S')}
  Estado:     No disponible / Error de conexión

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Es posible que los correos no se estén entregando correctamente.
Nuestro equipo revisará el sistema de inmediato.

Ante cualquier consulta urgente, contáctenos en {support}.

Saludos,
{company}
"""

    try:
        from emailmon.services import send_tracked_email
        send_tracked_email(subject=subject, body=body, to=recipients,
                           category="incident", client=client)
    except Exception:
        try:
            from django.core.mail import send_mail
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                      recipients, fail_silently=True)
        except Exception as e:
            logger.error(f"Error enviando alerta SMTP: {e}")

    try:
        MaintenanceIncident.objects.create(
            client=client,
            title=f"Problema SMTP detectado: {smtp_host}",
            severity="high",
            category="email",
            notify_email=False,
            description=f"Error detectado: {error_msg[:300]}\nServidor: {smtp_host}",
        )
    except Exception as e:
        logger.error(f"Error creando incidente SMTP: {e}")

def models_Q(**kwargs):
    from django.db.models import Q
    return Q(**kwargs)
