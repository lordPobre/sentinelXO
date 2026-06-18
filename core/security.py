"""
Sentinel XO — Postura de Seguridad M365
Consulta Secure Score y estado de MFA vía Microsoft Graph API.
"""
import logging
import requests as req_lib
from collections import defaultdict
from core.models import SecurityCheck, SecuritySnapshot, SecurityAnomalyEvent, SignInAnomalyEvent, SoftwareSnapshot, NetworkSnapshot
from monitoring.services import get_graph_token
from django.conf import settings
from emailmon.services import send_tracked_email
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger("sentinel.security")


def check_m365_security_posture(client) -> dict:
    """
    Consulta la postura de seguridad M365 de un cliente:
      1. Secure Score (Microsoft) — puntaje global de seguridad del tenant
      2. Estado de MFA — cuántos usuarios tienen autenticación multifactor registrada

    Guarda el resultado como SecurityCheck y lo retorna.
    """

    result = {
        "client":  str(client),
        "overall": "ok",
        "checks":  {},
        "errors":  [],
    }

    if not (hasattr(client, "m365_tenant") and client.m365_tenant and client.m365_tenant.is_active):
        return {**result, "overall": "not_configured",
                "errors": ["Tenant M365 no configurado para este cliente"]}

    tenant = client.m365_tenant

    # ── 1. Token ────────────────────────────────────────────────────────────
    try:
        token = get_graph_token(
            tenant.tenant_id,
            tenant.azure_client_id,
            tenant.azure_client_secret,
        )
    except Exception as e:
        SecurityCheck.objects.create(
            client=client, error_msg=f"Auth fallida: {e}"[:500],
            check_details={"overall": "error"},
        )
        return {**result, "overall": "error", "errors": [f"Auth fallida: {e}"]}

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    secure_score, secure_score_max = None, None
    mfa_registered, mfa_total = None, None

    # ── 2. Secure Score ─────────────────────────────────────────────────────
    try:
        resp = req_lib.get(
            "https://graph.microsoft.com/v1.0/security/secureScores?$top=1",
            headers=headers, timeout=15,
        )
        if resp.status_code == 200:
            values = resp.json().get("value", [])
            if values:
                latest = values[0]
                secure_score     = latest.get("currentScore")
                secure_score_max = latest.get("maxScore")
                result["checks"]["secure_score"] = {
                    "status": "ok",
                    "label":  "Secure Score",
                    "value":  secure_score,
                    "max":    secure_score_max,
                    "detail": f"{secure_score:.0f} / {secure_score_max:.0f}" if secure_score is not None else "—",
                }
            else:
                result["checks"]["secure_score"] = {
                    "status": "skipped", "label": "Secure Score",
                    "detail": "Sin datos de Secure Score aún",
                }
        elif resp.status_code == 403:
            result["checks"]["secure_score"] = {
                "status": "skipped", "label": "Secure Score",
                "detail": "Sin permiso SecurityEvents.Read.All",
            }
            result["errors"].append("Secure Score: sin permiso SecurityEvents.Read.All")
        else:
            result["checks"]["secure_score"] = {
                "status": "error", "label": "Secure Score",
                "error":  f"HTTP {resp.status_code}",
            }
            result["overall"] = "warning"
    except Exception as e:
        result["checks"]["secure_score"] = {
            "status": "error", "label": "Secure Score", "error": str(e)[:150],
        }
        result["overall"] = "warning"
        logger.error(f"Security check error (secureScore) para {client}: {e}")

    # ── 3. Estado de MFA por usuario ────────────────────────────────────────

    try:
        users_resp = req_lib.get(
            "https://graph.microsoft.com/v1.0/users"
            "?$select=id,userPrincipalName,accountEnabled&$top=999",
            headers=headers, timeout=15,
        )
        if users_resp.status_code == 200:
            all_users = [u for u in users_resp.json().get("value", [])
                         if u.get("accountEnabled", True)]
            mfa_total      = len(all_users)
            mfa_registered = 0
            no_mfa_users   = []

            non_mfa_methods = {"#microsoft.graph.passwordAuthenticationMethod"}

            for u in all_users:
                uid = u.get("id")
                try:
                    m_resp = req_lib.get(
                        f"https://graph.microsoft.com/v1.0/users/{uid}/authentication/methods",
                        headers=headers, timeout=10,
                    )
                    if m_resp.status_code == 200:
                        methods   = m_resp.json().get("value", [])
                        method_types = {m.get("@odata.type") for m in methods}
                        has_mfa = bool(method_types - non_mfa_methods)
                        if has_mfa:
                            mfa_registered += 1
                        else:
                            no_mfa_users.append(u.get("userPrincipalName"))
                    else:
                        mfa_total -= 1
                except Exception:
                    mfa_total -= 1

            pct = round((mfa_registered / mfa_total * 100), 1) if mfa_total else 0
            result["checks"]["mfa"] = {
                "status":    "ok" if pct >= 90 else ("warning" if pct >= 50 else "error"),
                "label":     "Cobertura MFA",
                "registered": mfa_registered,
                "total":      mfa_total,
                "percent":    pct,
                "detail":     f"{mfa_registered}/{mfa_total} usuarios ({pct}%)",
                "no_mfa_users": no_mfa_users[:10],
            }
            if pct < 90:
                result["overall"] = "warning" if result["overall"] == "ok" else result["overall"]
                result["errors"].append(f"MFA: solo {pct}% de usuarios con MFA registrado")

        elif users_resp.status_code == 403:
            body_txt = users_resp.text[:300]
            logger.error(f"MFA check 403 (users) para {client}: {body_txt}")
            result["checks"]["mfa"] = {
                "status": "skipped", "label": "Cobertura MFA",
                "detail": "Sin permiso User.Read.All / UserAuthenticationMethod.Read.All",
                "raw_error": body_txt,
            }
            result["errors"].append(f"MFA: sin permiso — {body_txt[:150]}")
        else:
            body_txt = users_resp.text[:300]
            logger.error(f"MFA check HTTP {users_resp.status_code} para {client}: {body_txt}")
            result["checks"]["mfa"] = {
                "status": "error", "label": "Cobertura MFA",
                "error":  f"HTTP {users_resp.status_code}",
                "raw_error": body_txt,
            }
            result["overall"] = "warning"
    except Exception as e:
        result["checks"]["mfa"] = {
            "status": "error", "label": "Cobertura MFA", "error": str(e)[:150],
        }
        result["overall"] = "warning"
        logger.error(f"Security check error (MFA) para {client}: {e}")

    # ── Guardar snapshot ─────────────────────────────────────────────────────
    err_summary = "; ".join(result["errors"])[:500] if result["errors"] else ""
    SecurityCheck.objects.create(
        client=client,
        secure_score=secure_score,
        secure_score_max=secure_score_max,
        mfa_registered=mfa_registered,
        mfa_total=mfa_total,
        check_details=result["checks"],
        error_msg=err_summary,
    )

    logger.info(f"Security check OK para {client}: secure_score={secure_score}/{secure_score_max}, "
                f"mfa={mfa_registered}/{mfa_total}")

    return result


# ── Detección de anomalías vía agente (huella de seguridad) ───────────────────

def _startup_key(item):
    """Clave normalizada (source sin sufijo de bits + nombre) para un item de inicio."""
    import re
    source = re.sub(r"\s*\((64|32)bit\)", "", item.get("source", ""))
    return f"{source}::{item.get('name','')}"


def _normalize_startup(items):
    """Convierte lista de dicts de programas de inicio en set de claves comparables.
    Ignora el sufijo (64bit)/(32bit) del source para no generar falsos positivos
    si cambia la vista de registro detectada entre versiones del agente."""
    return {_startup_key(i) for i in (items or [])}


def _normalize_tasks(items):
    """Convierte lista de dicts de tareas programadas en set de nombres."""
    return {i.get("name", "") for i in (items or []) if i.get("name")}


def process_security_snapshot(device, snapshot_data: dict) -> list:
    """
    Compara la huella de seguridad recibida del agente con la última conocida
    para el dispositivo. Crea SecurityAnomalyEvent por cada cambio detectado
    y actualiza el snapshot. Retorna la lista de anomalías creadas.

    snapshot_data: {"local_admins": [...], "startup_programs": [...], "scheduled_tasks": [...]}
    """
    new_admins  = set(snapshot_data.get("local_admins") or [])
    new_startup = snapshot_data.get("startup_programs") or []
    new_tasks   = snapshot_data.get("scheduled_tasks") or []

    new_startup_set = _normalize_startup(new_startup)
    new_tasks_set   = _normalize_tasks(new_tasks)

    snap, created = SecuritySnapshot.objects.get_or_create(device=device)
    anomalies = []

    if created:
        snap.local_admins     = sorted(new_admins)
        snap.startup_programs = new_startup
        snap.scheduled_tasks  = new_tasks
        snap.save(update_fields=["local_admins", "startup_programs", "scheduled_tasks", "updated_at"])
        logger.info(f"Huella de seguridad inicial registrada para {device.display_name}")
        return anomalies

    old_admins      = set(snap.local_admins or [])
    old_startup_set = _normalize_startup(snap.startup_programs)
    old_tasks_set   = _normalize_tasks(snap.scheduled_tasks)

    # ── Administradores locales ────────────────────────────────────────────
    for added in (new_admins - old_admins):
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="new_admin", severity="critical",
            detail=f"Nueva cuenta con privilegios de administrador: {added}",
        ))
    for removed in (old_admins - new_admins):
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="removed_admin", severity="info",
            detail=f"Cuenta removida del grupo de administradores: {removed}",
        ))

    # ── Programas de inicio ─────────────────────────────────────────────────
    new_startup_by_key = {_startup_key(i): i for i in new_startup}
    for added_key in (new_startup_set - old_startup_set):
        item = new_startup_by_key.get(added_key, {})
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="new_startup", severity="warning",
            detail=f"Nuevo programa de inicio: {item.get('name','?')} "
                   f"({item.get('source','')}) → {item.get('command','')[:150]}",
        ))
    old_startup_by_key = {_startup_key(i): i for i in (snap.startup_programs or [])}
    for removed_key in (old_startup_set - new_startup_set):
        item = old_startup_by_key.get(removed_key, {})
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="removed_startup", severity="info",
            detail=f"Programa de inicio eliminado: {item.get('name','?')} ({item.get('source','')})",
        ))

    # ── Tareas programadas ───────────────────────────────────────────────────
    for added in (new_tasks_set - old_tasks_set):
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="new_task", severity="warning",
            detail=f"Nueva tarea programada: {added}",
        ))
    for removed in (old_tasks_set - new_tasks_set):
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="removed_task", severity="info",
            detail=f"Tarea programada eliminada: {removed}",
        ))

    if anomalies:
        SecurityAnomalyEvent.objects.bulk_create(anomalies)
        logger.warning(f"Anomalías de seguridad detectadas en {device.display_name}: "
                       f"{len(anomalies)} ({', '.join(a.anomaly_type for a in anomalies)})")

    snap.local_admins     = sorted(new_admins)
    snap.startup_programs = new_startup
    snap.scheduled_tasks  = new_tasks
    snap.save(update_fields=["local_admins", "startup_programs", "scheduled_tasks", "updated_at"])

    return anomalies


def notify_security_anomalies(device, anomalies: list):
    """Envía un email consolidado por las anomalías de seguridad detectadas."""
    if not anomalies:
        return

    client = device.client
    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    recipients = client.get_alert_recipients()
    if not recipients:
        return

    has_critical = any(a.severity == "critical" for a in anomalies)
    icon = "🚨" if has_critical else "⚠️"

    lines = []
    for a in anomalies:
        sev_icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(a.severity, "•")
        lines.append(f"{sev_icon} {a.get_anomaly_type_display()}: {a.detail}")

    subject = f"{icon} [{company}] Cambios de seguridad detectados en {device.display_name}"
    message = (
        f"Estimado equipo de {client.company_name},\n\n"
        f"Sentinel XO detectó los siguientes cambios en la configuración de seguridad "
        f"del equipo {device.display_name}:\n\n"
        + "\n".join(lines) +
        f"\n\nSi estos cambios no fueron realizados por su equipo de TI, "
        f"recomendamos revisar el equipo de inmediato.\n\n"
        f"— {company}"
    )

    try:
        send_tracked_email(
            subject=subject, body=message, to=recipients,
            category="alert", client=client,
        )
        SecurityAnomalyEvent.objects.filter(
            id__in=[a.id for a in anomalies]
        ).update(notified=True)
        logger.info(f"Alerta de seguridad enviada para {device.display_name} "
                    f"({len(anomalies)} anomalías) → {recipients}")
    except Exception as e:
        logger.error(f"Error enviando alerta de seguridad para {device.display_name}: {e}")

    critical = [a for a in anomalies if a.severity == "critical"]
    if critical:
        from core.notifications_telegram import notify_telegram
        tg_lines = [f"🔴 {a.get_anomaly_type_display()}: {a.detail}" for a in critical]
        notify_telegram(
            client,
            f"🚨 <b>{company}</b>\n\n"
            f"Cambios críticos de seguridad en <b>{device.display_name}</b>:\n\n"
            + "\n".join(tg_lines)
        )


# ── Monitor de inicios de sesión sospechosos M365 ──────────────────────────────
IMPOSSIBLE_TRAVEL_WINDOW_HOURS = 3 
NON_RISK_VALUES = {None, "none", "hidden", ""}


def check_signin_anomalies(client) -> list:
    """
    Consulta los inicios de sesión recientes de un cliente vía Graph API y
    detecta:
      - Inicios de sesión desde un país nuevo (no visto antes)
      - "Viaje imposible": el mismo usuario inicia sesión desde dos países
        distintos en menos de IMPOSSIBLE_TRAVEL_WINDOW_HOURS
      - Inicios de sesión que Microsoft marcó como riesgosos

    Crea SignInAnomalyEvent por cada anomalía y notifica por email.
    Retorna la lista de anomalías creadas.
    """
    anomalies = []

    if not (hasattr(client, "m365_tenant") and client.m365_tenant and client.m365_tenant.is_active):
        return anomalies

    tenant = client.m365_tenant

    try:
        token = get_graph_token(
            tenant.tenant_id, tenant.azure_client_id, tenant.azure_client_secret,
        )
    except Exception as e:
        logger.error(f"check_signin_anomalies: auth fallida para {client}: {e}")
        return anomalies

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    now = timezone.now()
    since = tenant.last_signin_check or (now - timedelta(hours=24))
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        resp = req_lib.get(
            "https://graph.microsoft.com/v1.0/auditLogs/signIns"
            f"?$filter=createdDateTime ge {since_iso}"
            "&$top=200&$orderby=createdDateTime asc",
            headers=headers, timeout=20,
        )
    except Exception as e:
        logger.error(f"check_signin_anomalies: error de red para {client}: {e}")
        return anomalies

    if resp.status_code == 403:
        logger.warning(f"check_signin_anomalies: sin permiso AuditLog.Read.All para {client}: "
                       f"{resp.text[:200]}")
        return anomalies
    if resp.status_code != 200:
        logger.error(f"check_signin_anomalies: HTTP {resp.status_code} para {client}: {resp.text[:200]}")
        return anomalies

    signins = resp.json().get("value", [])

    successes = [s for s in signins if (s.get("status") or {}).get("errorCode") == 0]

    known_countries = set(tenant.known_countries or [])
    is_first_run = len(known_countries) == 0 and tenant.last_signin_check is None

    if is_first_run:
        for s in successes:
            country = ((s.get("location") or {}).get("countryOrRegion") or "").strip()
            if country:
                known_countries.add(country)
        tenant.known_countries = sorted(known_countries)
        tenant.last_signin_check = now
        tenant.save(update_fields=["known_countries", "last_signin_check"])
        logger.info(f"check_signin_anomalies: línea base registrada para {client} "
                    f"({len(known_countries)} países: {', '.join(sorted(known_countries)) or '—'})")
        return anomalies

    # ── 1. Países nuevos + 3. Riesgo marcado por Microsoft ──────────────────
    new_countries_seen = set()
    for s in successes:
        user    = s.get("userPrincipalName", "?")
        country = ((s.get("location") or {}).get("countryOrRegion") or "").strip()
        ip      = (s.get("ipAddress") or "?")
        app     = s.get("appDisplayName", "?")
        created = s.get("createdDateTime", "")
        city    = ((s.get("location") or {}).get("city") or "")
        loc_txt = f"{city}, {country}" if city else (country or "ubicación desconocida")

        if country and country not in known_countries:
            anomalies.append(SignInAnomalyEvent(
                client=client, anomaly_type="new_country", severity="warning",
                detail=(f"Inicio de sesión desde un país no habitual: {user} "
                        f"→ {loc_txt} · IP {ip} · App: {app} · {created}"),
            ))
            new_countries_seen.add(country)

        risk = s.get("riskLevelDuringSignIn")
        if risk not in NON_RISK_VALUES:
            anomalies.append(SignInAnomalyEvent(
                client=client, anomaly_type="risky_signin",
                severity="critical" if risk == "high" else "warning",
                detail=(f"Microsoft marcó este inicio de sesión como riesgo '{risk}': {user} "
                        f"→ {loc_txt} · IP {ip} · App: {app} · {created}"),
            ))

    # ── 2. Viaje imposible ────────────────────────────────────────────────
    by_user = defaultdict(list)
    for s in successes:
        country = ((s.get("location") or {}).get("countryOrRegion") or "").strip()
        created = s.get("createdDateTime")
        if country and created:
            try:
                dt = timezone.datetime.fromisoformat(created.replace("Z", "+00:00"))
            except Exception:
                continue
            by_user[s.get("userPrincipalName", "?")].append((dt, country, s))

    for user, entries in by_user.items():
        entries.sort(key=lambda x: x[0])
        for i in range(1, len(entries)):
            dt_prev, country_prev, s_prev = entries[i-1]
            dt_curr, country_curr, s_curr = entries[i]
            if country_curr == country_prev:
                continue
            delta = dt_curr - dt_prev
            if delta <= timedelta(hours=IMPOSSIBLE_TRAVEL_WINDOW_HOURS):
                ip_prev = s_prev.get("ipAddress", "?")
                ip_curr = s_curr.get("ipAddress", "?")
                hours = delta.total_seconds() / 3600
                anomalies.append(SignInAnomalyEvent(
                    client=client, anomaly_type="impossible_travel", severity="critical",
                    detail=(f"Viaje imposible detectado para {user}: sesión desde {country_prev} "
                            f"({ip_prev}) y {hours:.1f}h después desde {country_curr} ({ip_curr}) "
                            f"→ {dt_prev.strftime('%d/%m %H:%M')} → {dt_curr.strftime('%d/%m %H:%M')} UTC"),
                ))

    if anomalies:
        SignInAnomalyEvent.objects.bulk_create(anomalies)
        logger.warning(f"check_signin_anomalies: {len(anomalies)} anomalía(s) para {client} "
                       f"({', '.join(a.anomaly_type for a in anomalies)})")

    if new_countries_seen:
        known_countries |= new_countries_seen
        tenant.known_countries = sorted(known_countries)

    tenant.last_signin_check = now
    tenant.save(update_fields=["known_countries", "last_signin_check"])

    return anomalies


def notify_signin_anomalies(client, anomalies: list):
    """Envía un email consolidado por las anomalías de inicio de sesión detectadas."""
    if not anomalies:
        return

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    recipients = client.get_alert_recipients()
    if not recipients:
        return

    has_critical = any(a.severity == "critical" for a in anomalies)
    icon = "🚨" if has_critical else "🌍"

    lines = []
    for a in anomalies:
        sev_icon = {"critical": "🔴", "warning": "🟡", "info": "ℹ️"}.get(a.severity, "•")
        lines.append(f"{sev_icon} {a.get_anomaly_type_display()}: {a.detail}")

    subject = f"{icon} [{company}] Inicios de sesión sospechosos en {client.company_name}"
    message = (
        f"Estimado equipo de {client.company_name},\n\n"
        f"Sentinel XO detectó los siguientes inicios de sesión inusuales en Microsoft 365:\n\n"
        + "\n".join(lines) +
        f"\n\nSi estos inicios de sesión no corresponden a actividad esperada (viajes, "
        f"nuevos dispositivos, VPN), recomendamos revisar las cuentas afectadas, "
        f"forzar el cierre de sesión y restablecer la contraseña.\n\n"
        f"— {company}"
    )

    try:
        send_tracked_email(
            subject=subject, body=message, to=recipients,
            category="alert", client=client,
        )
        SignInAnomalyEvent.objects.filter(
            id__in=[a.id for a in anomalies]
        ).update(notified=True)
        logger.info(f"Alerta de sign-in enviada para {client} "
                    f"({len(anomalies)} anomalías) → {recipients}")
    except Exception as e:
        logger.error(f"Error enviando alerta de sign-in para {client}: {e}")

    critical = [a for a in anomalies if a.severity == "critical"]
    if critical:
        from core.notifications_telegram import notify_telegram
        tg_lines = [f"🔴 {a.get_anomaly_type_display()}: {a.detail}" for a in critical]
        notify_telegram(
            client,
            f"🚨 <b>{company}</b>\n\n"
            f"Inicios de sesión críticos detectados en <b>{client.company_name}</b> (M365):\n\n"
            + "\n".join(tg_lines)
        )

# ── Inventario de software y detección de cambios ──────────────────────────────

def process_software_snapshot(device, software_list: list) -> list:
    """
    Compara el inventario de software recibido del agente con el último
    conocido para el dispositivo. Crea SecurityAnomalyEvent por cada programa
    nuevo o desinstalado, y actualiza el snapshot. Retorna las anomalías creadas.

    software_list: [{"name": ..., "version": ..., "publisher": ...}, ...]
    """
    def _sw_key(item):
        return (item.get("name", "").strip().lower(), str(item.get("version", "")).strip())

    new_set = {_sw_key(i) for i in software_list}
    new_by_key = {_sw_key(i): i for i in software_list}

    snap, created = SoftwareSnapshot.objects.get_or_create(device=device)
    anomalies = []

    if created or not snap.software_list:
        snap.software_list = software_list
        snap.save(update_fields=["software_list", "updated_at"])
        logger.info(f"Inventario de software inicial registrado para {device.display_name} "
                    f"({len(software_list)} programas)")
        return anomalies

    old_set = {_sw_key(i) for i in (snap.software_list or [])}
    old_by_key = {_sw_key(i): i for i in (snap.software_list or [])}

    for added_key in (new_set - old_set):
        item = new_by_key.get(added_key, {})
        ver = f" v{item.get('version')}" if item.get("version") else ""
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="new_software", severity="info",
            detail=(f"Nuevo software instalado: {item.get('name','?')}{ver} "
                    f"→ Publicador: {item.get('publisher') or 'desconocido'}"),
        ))

    for removed_key in (old_set - new_set):
        item = old_by_key.get(removed_key, {})
        ver = f" v{item.get('version')}" if item.get("version") else ""
        anomalies.append(SecurityAnomalyEvent(
            device=device, anomaly_type="removed_software", severity="info",
            detail=f"Software desinstalado: {item.get('name','?')}{ver}",
        ))

    if anomalies:
        SecurityAnomalyEvent.objects.bulk_create(anomalies)
        logger.info(f"Cambios de software detectados en {device.display_name}: "
                    f"{len(anomalies)} ({sum(1 for a in anomalies if a.anomaly_type=='new_software')} nuevos, "
                    f"{sum(1 for a in anomalies if a.anomaly_type=='removed_software')} desinstalados)")

    snap.software_list = software_list
    if anomalies:
        snap.cve_analysis = None
        snap.cve_checked_at = None
        snap.save(update_fields=["software_list", "cve_analysis", "cve_checked_at", "updated_at"])
    else:
        snap.save(update_fields=["software_list", "updated_at"])

    return anomalies


# ─── Estabilidad y seguridad de red ──────────────────────────────────────────

def update_network_stability(device, network_data: dict):
    """
    Actualiza la parte de estabilidad del NetworkSnapshot desde la telemetría
    (latencia, pérdida de paquetes, señal WiFi). No genera anomalías — solo
    refresca los valores. Llamado en cada telemetría que traiga calidad de red.
    """
    has_quality = any(k in network_data for k in ("latency_ms", "packet_loss_percent", "wifi"))
    if not has_quality:
        return

    snap, _ = NetworkSnapshot.objects.get_or_create(device=device)
    snap.latency_ms = network_data.get("latency_ms")
    snap.packet_loss_percent = network_data.get("packet_loss_percent")

    wifi = network_data.get("wifi") or {}
    if wifi:
        snap.wifi_ssid = wifi.get("ssid") or ""
        snap.wifi_signal_percent = wifi.get("signal_percent")

    snap.save(update_fields=[
        "latency_ms", "packet_loss_percent", "wifi_ssid",
        "wifi_signal_percent", "updated_at",
    ])


def _evaluate_network_risk(snap) -> tuple:
    """
    Evalúa el nivel de riesgo de la red. Devuelve (risk_level, reasons).
    """
    reasons = []
    level = "ok"

    if snap.is_open_wifi:
        reasons.append("Conectado a una red WiFi abierta (sin cifrado).")
        level = "critical"
    elif snap.wifi_encryption:
        enc = snap.wifi_encryption.lower()
        if "wep" in enc or ("wpa" in enc and "wpa2" not in enc and "wpa3" not in enc):
            reasons.append(f"Cifrado WiFi débil u obsoleto: {snap.wifi_encryption}.")
            level = "warning"

    if snap.firewall_all_on is False:
        off = [fw.get("name") for fw in snap.firewall if not fw.get("enabled")]
        reasons.append(f"Firewall desactivado en: {', '.join(off)}.")
        level = "critical"

    if snap.packet_loss_percent is not None and snap.packet_loss_percent >= 10:
        reasons.append(f"Pérdida de paquetes elevada: {snap.packet_loss_percent:.0f}%.")
        if level == "ok":
            level = "warning"

    if snap.latency_ms is not None and snap.latency_ms >= 200:
        reasons.append(f"Latencia alta hacia el gateway: {snap.latency_ms:.0f} ms.")
        if level == "ok":
            level = "warning"

    return level, reasons


def process_network_security(device, net_sec: dict) -> list:
    """
    Procesa la seguridad de red recibida con el snapshot de seguridad. Guarda
    los datos, evalúa el riesgo, y compara contra el estado anterior para
    detectar cambios (WiFi abierta, firewall apagado, cambio de red/DNS).
    Retorna lista de anomalías creadas.
    """
    snap, created = NetworkSnapshot.objects.get_or_create(device=device)

    old_ssid = snap.wifi_ssid
    old_dns = set(snap.dns_servers or [])
    old_fw_on = snap.firewall_all_on
    old_open_wifi = snap.is_open_wifi

    snap.wifi_encryption  = net_sec.get("wifi_encryption") or ""
    snap.network_category = net_sec.get("network_category") or ""
    snap.firewall         = net_sec.get("firewall") or []
    snap.dns_servers      = net_sec.get("dns_servers") or []
    if net_sec.get("wifi_ssid"):
        snap.wifi_ssid = net_sec.get("wifi_ssid")

    level, reasons = _evaluate_network_risk(snap)
    snap.risk_level = level
    snap.risk_reasons = reasons
    snap.security_checked_at = timezone.now()
    snap.save()

    anomalies = []

    if created:
        logger.info(f"Postura de red inicial registrada para {device.display_name}")
        return anomalies

    def _anomaly(atype, severity, detail):
        ev = SecurityAnomalyEvent.objects.create(
            device=device, anomaly_type=atype, severity=severity, detail=detail,
        )
        anomalies.append(ev)

    if snap.is_open_wifi and not old_open_wifi:
        _anomaly("open_wifi", "warning",
                 f"El equipo se conectó a una red WiFi abierta: {snap.wifi_ssid or '(desconocida)'}.")

    if old_fw_on is not False and snap.firewall_all_on is False:
        off = [fw.get("name") for fw in snap.firewall if not fw.get("enabled")]
        _anomaly("firewall_off", "critical",
                 f"Firewall desactivado en: {', '.join(off)}.")

    if old_ssid and snap.wifi_ssid and old_ssid != snap.wifi_ssid:
        _anomaly("network_change", "info",
                 f"Cambio de red WiFi: '{old_ssid}' → '{snap.wifi_ssid}'.")

    new_dns = set(snap.dns_servers or [])
    if old_dns and new_dns and old_dns != new_dns:
        added = new_dns - old_dns
        if added:
            _anomaly("dns_change", "warning",
                     f"Cambio en servidores DNS. Nuevos: {', '.join(sorted(added))}.")

    return anomalies
