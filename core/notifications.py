"""
Notificaciones por email para incidentes Sentinel XO.
Se llama automáticamente al crear un incidente desde el dashboard.
"""
import logging
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("perseus")

SEVERITY_LABELS = {
    "low":      "Baja",
    "medium":   "Media",
    "high":     "Alta",
    "critical": "Crítica",
}

SEVERITY_EMOJIS = {
    "low":      "🔵",
    "medium":   "🟡",
    "high":     "🟠",
    "critical": "🔴",
}

CATEGORY_LABELS = {
    "hardware": "Hardware / Equipo",
    "domain":   "Dominio",
    "email":    "Email / SMTP",
    "license":  "Licencia M365",
    "network":  "Red",
    "other":    "Otro",
}


def _get_recipients(incident) -> list[str]:
    """
    Determina los destinatarios según la categoría del incidente.
    - Hardware / Red → contacto del cliente (usuario del equipo)
    - Dominio / Email / Licencia → contacto del cliente (jefe / responsable TI)
    Siempre incluye el email del cliente.
    """
    # Usar el método centralizado del modelo — incluye contact_email + alert_emails
    recipients = list(incident.client.get_alert_recipients())

    # Usuarios del portal también reciben si es incidente de hardware
    if incident.device and incident.category == "hardware":
        for user in incident.client.portal_users.filter(email__isnull=False):
            if user.email and user.email not in recipients:
                recipients.append(user.email)

    return list(set(recipients))


def _build_subject(incident) -> str:
    emoji = SEVERITY_EMOJIS.get(incident.severity, "⚠️")
    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    return (
        f"{emoji} [{company}] Incidente {incident.get_severity_display()}: "
        f"{incident.title[:60]}"
    )


def _build_body(incident) -> str:
    company      = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support      = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@sentinelxo.dev")
    category     = CATEGORY_LABELS.get(incident.category, incident.category)
    severity     = SEVERITY_LABELS.get(incident.severity, incident.severity)
    created_at   = incident.created_at.strftime("%d/%m/%Y a las %H:%M")

    # Detalle específico según categoría
    detail_lines = []
    if incident.category == "hardware" and incident.device:
        detail_lines += [
            f"  Equipo:          {incident.device.display_name}",
            f"  Sistema:         {incident.device.os or '—'}",
            f"  Último contacto: {incident.device.last_seen.strftime('%d/%m/%Y %H:%M') if incident.device.last_seen else '—'}",
        ]
    elif incident.category == "domain":
        # Buscar dominios con problemas del cliente
        domains = incident.client.domains.filter(
            status__in=["critical", "warning", "expired"]
        )
        if domains.exists():
            detail_lines.append("  Dominios en riesgo:")
            for d in domains:
                days = d.days_until_expiry
                estado = "VENCIDO" if days and days < 0 else f"{days} días" if days else "—"
                detail_lines.append(f"    • {d.fqdn} → {estado}")
    elif incident.category == "email":
        detail_lines += [
            "  Se ha detectado un problema con el sistema de email.",
            "  Por favor verifique que los correos se estén enviando correctamente.",
        ]
    elif incident.category == "license":
        licenses = incident.client.m365_licenses.filter(consumed_licenses__gte=models_f_total())
        if licenses.exists():
            detail_lines.append("  Licencias sin disponibilidad:")
            for l in licenses:
                detail_lines.append(f"    • {l.friendly_name}: {l.consumed_licenses}/{l.total_licenses}")

    detail_block = "\n".join(detail_lines) if detail_lines else ""

    body = f"""Estimado equipo de {incident.client.company_name},

Se ha registrado un nuevo incidente en el sistema de monitoreo Sentinel XO.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INCIDENTE DETECTADO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Título:     {incident.title}
  Categoría:  {category}
  Severidad:  {severity}
  Fecha:      {created_at}
  Estado:     Abierto — requiere atención
"""

    if detail_block:
        body += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DETALLE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{detail_block}
"""

    if incident.description:
        body += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  DESCRIPCIÓN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  {incident.description}
"""

    body += f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Nuestro equipo ya está al tanto de este incidente y tomará las medidas necesarias.
Nos pondremos en contacto con usted a la brevedad.

Ante cualquier consulta urgente, contáctenos en {support}.

Saludos,
{company}
"""
    return body


def models_f_total():
    from django.db.models import F
    return F("total_licenses")


def notify_incident_created(incident) -> bool:
    """
    Envía notificación por email al crear un incidente.
    Retorna True si el email se envió correctamente.
    """
    if not incident.notify_email:
        logger.info(f"Notificación desactivada para incidente #{incident.pk}")
        return False

    recipients = _get_recipients(incident)
    if not recipients:
        logger.warning(f"Sin destinatarios para incidente #{incident.pk}")
        return False

    subject = _build_subject(incident)
    body    = _build_body(incident)

    try:
        from emailmon.services import send_tracked_email
        success = send_tracked_email(
            subject=subject,
            body=body,
            to=recipients,
            category="incident",
            client=incident.client,
        )
        if success:
            logger.info(
                f"Notificación enviada: [{incident.get_severity_display()}] "
                f"{incident.title[:50]} → {', '.join(recipients)}"
            )
        return success

    except Exception as e:
        # Fallback a send_mail si emailmon no está disponible
        try:
            from django.core.mail import send_mail
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL,
                      recipients, fail_silently=True)
            logger.info(f"Notificación enviada (fallback): {incident.title[:50]}")
            return True
        except Exception as e2:
            logger.error(f"Error enviando notificación de incidente: {e2}")
            return False


def notify_incident_resolved(incident) -> bool:
    """
    Envía notificación de resolución al cerrar un incidente.
    """
    recipients = _get_recipients(incident)
    if not recipients:
        return False

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    support = getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@sentinelxo.dev")
    resolved_at = incident.resolved_at.strftime("%d/%m/%Y a las %H:%M") if incident.resolved_at else "—"

    subject = f"✅ [{company}] Incidente resuelto: {incident.title[:60]}"
    body = f"""Estimado equipo de {incident.client.company_name},

Nos complace informarle que el siguiente incidente ha sido resuelto:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  INCIDENTE RESUELTO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  Título:     {incident.title}
  Severidad:  {incident.get_severity_display()}
  Resuelto:   {resolved_at}
  Estado:     ✅ Cerrado

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Si tiene alguna duda sobre las acciones tomadas, contáctenos en {support}.

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
            client=incident.client,
        )
    except Exception as e:
        logger.error(f"Error enviando notificación de resolución: {e}")
        return False
