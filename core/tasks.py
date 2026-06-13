"""
Sentinel XO — Tareas Celery de core (monitoreo de conectividad de agentes).
"""
import logging
from celery import shared_task
from django.utils import timezone
from django.conf import settings

logger = logging.getLogger("sentinel.tasks")


@shared_task(name="core.check_offline_devices")
def check_offline_devices():
    """
    Revisa todos los dispositivos activos y detecta cuáles llevan más de
    HardwareDevice.OFFLINE_THRESHOLD_MINUTES sin reportar telemetría.

    - Si un dispositivo pasa a offline → crea MaintenanceIncident + email.
    - Si un dispositivo que estaba offline vuelve a reportar → email de
      recuperación y limpia el estado.

    Pensada para ejecutarse cada 5 minutos vía Celery Beat (Periodic Task
    configurada en Django Admin).
    """
    from core.models import HardwareDevice, MaintenanceIncident
    from emailmon.services import send_tracked_email

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    now = timezone.now()

    devices = HardwareDevice.objects.filter(is_active=True, client__is_active=True).select_related("client")

    went_offline = 0
    recovered = 0

    for device in devices:
        currently_offline = not device.is_online

        # ── Caso 1: estaba online, ahora offline ──────────────────────────
        if currently_offline and not device.is_offline:
            device.is_offline = True
            device.offline_since = now
            device.offline_notified = False
            device.save(update_fields=["is_offline", "offline_since", "offline_notified"])
            logger.warning(
                f"Dispositivo offline: {device.display_name} ({device.client}) — "
                f"último contacto: {device.last_seen}"
            )
            went_offline += 1
            continue

        # ── Caso 2: ya estaba offline, sigue offline → ¿notificar? ────────
        if currently_offline and device.is_offline and not device.offline_notified:
            minutes = device.minutes_since_last_seen
            last_seen_local = timezone.localtime(device.last_seen) if device.last_seen else None

            try:
                incident = MaintenanceIncident.objects.create(
                    client=device.client,
                    device=device,
                    title=f"Equipo sin conexión: {device.display_name}",
                    severity="high",
                    category="connectivity",
                    notify_email=False,
                    description=(
                        f"El agente de monitoreo de {device.display_name} dejó de reportar "
                        f"telemetría.\n\n"
                        f"Último contacto: {last_seen_local.strftime('%d/%m/%Y %H:%M:%S') if last_seen_local else '—'}\n"
                        f"Tiempo sin reportar: {minutes:.0f} minutos\n\n"
                        f"Posibles causas: el equipo está apagado, sin conexión a internet, "
                        f"o el servicio del agente Sentinel XO se detuvo."
                    ),
                )
                # Diagnóstico IA en background, igual que otros incidentes automáticos
                try:
                    import threading
                    from core.views_ai import diagnose_incident
                    def run_diagnosis():
                        diag = diagnose_incident(incident)
                        if diag:
                            incident.ai_diagnosis = diag
                            incident.save(update_fields=["ai_diagnosis"])
                    threading.Thread(target=run_diagnosis, daemon=True).start()
                except Exception as e:
                    logger.warning(f"Error iniciando diagnóstico IA para incidente offline: {e}")
            except Exception as e:
                logger.error(f"Error creando incidente offline para {device.display_name}: {e}")

            recipients = device.client.get_alert_recipients()
            if recipients:
                subject = f"🔴 [{company}] {device.display_name} sin conexión"
                message = (
                    f"Estimado equipo de {device.client.company_name},\n\n"
                    f"El equipo {device.display_name} dejó de reportar telemetría a Sentinel XO.\n\n"
                    f"Último contacto: {last_seen_local.strftime('%d/%m/%Y %H:%M:%S') if last_seen_local else '—'}\n"
                    f"Tiempo sin reportar: {minutes:.0f} minutos\n\n"
                    f"Esto puede indicar que el equipo está apagado, sin internet, o que el "
                    f"servicio del agente se detuvo. Si esto es esperado (mantenimiento, "
                    f"equipo apagado a propósito), puede ignorar esta alerta.\n\n"
                    f"— {company}"
                )
                try:
                    send_tracked_email(
                        subject=subject, body=message, to=recipients,
                        category="alert", client=device.client,
                    )
                    logger.info(f"Alerta offline enviada para {device.display_name} → {recipients}")
                except Exception as e:
                    logger.error(f"Error enviando alerta offline para {device.display_name}: {e}")

            device.offline_notified = True
            device.save(update_fields=["offline_notified"])

        # ── Caso 3: estaba offline, ahora volvió ──────────────────────────
        elif not currently_offline and device.is_offline:
            offline_since = device.offline_since
            device.is_offline = False
            device.offline_since = None
            device.offline_notified = False
            device.save(update_fields=["is_offline", "offline_since", "offline_notified"])
            recovered += 1

            recipients = device.client.get_alert_recipients()
            if recipients and offline_since:
                duration = now - offline_since
                hours, rem = divmod(int(duration.total_seconds()), 3600)
                minutes_d, _ = divmod(rem, 60)
                duration_txt = (f"{hours}h {minutes_d}min" if hours else f"{minutes_d} minutos")

                subject = f"🟢 [{company}] {device.display_name} reconectado"
                message = (
                    f"Estimado equipo de {device.client.company_name},\n\n"
                    f"El equipo {device.display_name} volvió a reportar telemetría a Sentinel XO.\n\n"
                    f"Estuvo sin conexión durante aproximadamente {duration_txt}.\n\n"
                    f"— {company}"
                )
                try:
                    send_tracked_email(
                        subject=subject, body=message, to=recipients,
                        category="alert", client=device.client,
                    )
                    logger.info(f"Alerta de reconexión enviada para {device.display_name} → {recipients}")
                except Exception as e:
                    logger.error(f"Error enviando alerta de reconexión para {device.display_name}: {e}")

    if went_offline or recovered:
        logger.info(f"check_offline_devices: {went_offline} nuevos offline, {recovered} reconectados")

    return {"went_offline": went_offline, "recovered": recovered, "checked": devices.count()}


@shared_task(name="core.backup_database")
def backup_database():
    """
    Backup semanal de los datos críticos de Sentinel XO.

    Usa `dumpdata` (portable, no requiere el binario pg_dump) para exportar
    los modelos de negocio — clientes, dispositivos, incidentes, seguridad,
    usuarios, etc. — excluyendo tablas de alto volumen que no son críticas
    para recuperación de desastres (telemetría detallada cada 5s, logs de
    auditoría, logs de email).

    El resultado se comprime con gzip y se envía por email como adjunto al
    correo configurado en SENTINEL_BACKUP_EMAIL.

    Pensada para ejecutarse semanalmente vía Celery Beat (Periodic Task
    configurada en Django Admin).
    """
    import gzip
    import io
    from django.core.management import call_command
    from emailmon.services import send_tracked_email

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    backup_email = getattr(settings, "SENTINEL_BACKUP_EMAIL", "")
    now = timezone.now()

    # Tablas de alto volumen / no críticas excluidas del backup
    EXCLUDED = [
        "core.telemetrysnapshot",
        "core.auditlog",
        "emailmon.emaillog",
        "admin.logentry",
        "contenttypes",
        "sessions.session",
        "django_celery_beat",
    ]

    if not backup_email:
        logger.error("backup_database: SENTINEL_BACKUP_EMAIL no configurado, abortando")
        return {"status": "error", "reason": "SENTINEL_BACKUP_EMAIL no configurado"}

    try:
        # ── 1. Generar dump JSON ────────────────────────────────────────────
        buf = io.StringIO()
        call_command(
            "dumpdata",
            exclude=EXCLUDED,
            natural_foreign=True,
            natural_primary=True,
            indent=None,
            stdout=buf,
        )
        json_data = buf.getvalue().encode("utf-8")
        raw_size = len(json_data)

        # ── 2. Comprimir con gzip ────────────────────────────────────────────
        gz_buf = io.BytesIO()
        with gzip.GzipFile(fileobj=gz_buf, mode="wb") as gz:
            gz.write(json_data)
        gz_data = gz_buf.getvalue()
        gz_size = len(gz_data)

        # ── 3. Verificar tamaño (límite Resend ~40MB) ───────────────────────
        MAX_SIZE = 35 * 1024 * 1024  # 35MB margen de seguridad
        if gz_size > MAX_SIZE:
            logger.error(
                f"backup_database: dump comprimido ({gz_size/1024/1024:.1f}MB) "
                f"excede el límite de adjunto ({MAX_SIZE/1024/1024:.0f}MB)"
            )
            send_tracked_email(
                subject=f"🔴 [{company}] Backup semanal FALLÓ — tamaño excedido",
                body=(
                    f"El backup semanal de la base de datos generó un archivo de "
                    f"{gz_size/1024/1024:.1f}MB, que excede el límite de adjunto de email "
                    f"({MAX_SIZE/1024/1024:.0f}MB).\n\n"
                    f"Considera configurar un destino de almacenamiento externo (S3, "
                    f"Cloudinary) para backups de mayor tamaño.\n\n"
                    f"— {company}"
                ),
                to=[backup_email],
                category="other",
            )
            return {"status": "error", "reason": "size_exceeded", "size_mb": round(gz_size/1024/1024, 1)}

        # ── 4. Enviar por email ──────────────────────────────────────────────
        filename = f"sentinelxo_backup_{now.strftime('%Y%m%d_%H%M')}.json.gz"
        subject = f"💾 [{company}] Backup semanal — {now.strftime('%d/%m/%Y')}"
        body = (
            f"Backup automático semanal de Sentinel XO.\n\n"
            f"Fecha: {timezone.localtime(now).strftime('%d/%m/%Y %H:%M')}\n"
            f"Tamaño sin comprimir: {raw_size/1024:.0f} KB\n"
            f"Tamaño comprimido: {gz_size/1024:.0f} KB\n\n"
            f"Este archivo contiene un dump JSON de los datos de negocio "
            f"(clientes, dispositivos, incidentes, configuración de seguridad, "
            f"usuarios, etc.) — comprimido con gzip.\n\n"
            f"Para restaurar:\n"
            f"  gunzip {filename}\n"
            f"  python manage.py loaddata {filename[:-3]}\n\n"
            f"Guarda este archivo en un lugar seguro (no lo dejes solo en el correo).\n\n"
            f"— {company}"
        )

        success = send_tracked_email(
            subject=subject, body=body, to=[backup_email],
            category="other",
            attachments=[(filename, gz_data, "application/gzip")],
        )

        if success:
            logger.info(f"backup_database: backup enviado a {backup_email} "
                       f"({gz_size/1024:.0f} KB comprimido)")
            return {"status": "ok", "size_kb": round(gz_size/1024, 1), "sent_to": backup_email}
        else:
            logger.error(f"backup_database: error enviando email a {backup_email}")
            return {"status": "error", "reason": "email_send_failed"}

    except Exception as e:
        logger.error(f"backup_database: error generando backup: {e}")
        try:
            send_tracked_email(
                subject=f"🔴 [{company}] Backup semanal FALLÓ",
                body=(
                    f"El backup semanal de la base de datos falló con el siguiente error:\n\n"
                    f"{e}\n\n— {company}"
                ),
                to=[backup_email],
                category="other",
            )
        except Exception:
            pass
        return {"status": "error", "reason": str(e)}
