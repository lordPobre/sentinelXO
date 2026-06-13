"""
Sentinel XO — Postura de Seguridad M365
Consulta Secure Score y estado de MFA vía Microsoft Graph API.
"""
import logging
import requests as req_lib
from monitoring.services import get_graph_token

logger = logging.getLogger("sentinel.security")


def check_m365_security_posture(client) -> dict:
    """
    Consulta la postura de seguridad M365 de un cliente:
      1. Secure Score (Microsoft) — puntaje global de seguridad del tenant
      2. Estado de MFA — cuántos usuarios tienen autenticación multifactor registrada

    Guarda el resultado como SecurityCheck y lo retorna.
    """
    from core.models import SecurityCheck

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
    # Requiere permiso SecurityEvents.Read.All (Application)
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
    # El reporte /reports/authenticationMethods/userRegistrationDetails requiere
    # Azure AD Premium P1/P2. Como alternativa compatible con cualquier tenant,
    # consultamos los métodos de autenticación registrados por cada usuario
    # individualmente vía /users/{id}/authentication/methods (Application:
    # UserAuthenticationMethod.Read.All).
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

            # Métodos que NO cuentan como MFA (solo contraseña)
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
                        # Si no podemos verificar un usuario, no lo contamos en el total
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
    from core.models import SecuritySnapshot, SecurityAnomalyEvent

    new_admins  = set(snapshot_data.get("local_admins") or [])
    new_startup = snapshot_data.get("startup_programs") or []
    new_tasks   = snapshot_data.get("scheduled_tasks") or []

    new_startup_set = _normalize_startup(new_startup)
    new_tasks_set   = _normalize_tasks(new_tasks)

    snap, created = SecuritySnapshot.objects.get_or_create(device=device)
    anomalies = []

    if created:
        # Primera huella — establece la línea base, sin generar anomalías
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

    # Actualizar snapshot con el estado actual
    snap.local_admins     = sorted(new_admins)
    snap.startup_programs = new_startup
    snap.scheduled_tasks  = new_tasks
    snap.save(update_fields=["local_admins", "startup_programs", "scheduled_tasks", "updated_at"])

    return anomalies


def notify_security_anomalies(device, anomalies: list):
    """Envía un email consolidado por las anomalías de seguridad detectadas."""
    if not anomalies:
        return

    from django.conf import settings
    from emailmon.services import send_tracked_email

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
        from core.models import SecurityAnomalyEvent
        SecurityAnomalyEvent.objects.filter(
            id__in=[a.id for a in anomalies]
        ).update(notified=True)
        logger.info(f"Alerta de seguridad enviada para {device.display_name} "
                    f"({len(anomalies)} anomalías) → {recipients}")
    except Exception as e:
        logger.error(f"Error enviando alerta de seguridad para {device.display_name}: {e}")


# ── Monitor de inicios de sesión sospechosos M365 ──────────────────────────────
# Usa /auditLogs/signIns — disponible sin Azure AD Premium P1/P2, solo requiere
# el permiso AuditLog.Read.All (Application) que ya se usa para la cobertura MFA.

IMPOSSIBLE_TRAVEL_WINDOW_HOURS = 3   # ventana máxima entre países distintos
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
    from django.utils import timezone
    from datetime import timedelta
    from core.models import SignInAnomalyEvent

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

    # Ventana de búsqueda: desde la última revisión, o últimas 24h en la primera ejecución
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

    # Solo inicios de sesión exitosos (errorCode == 0)
    successes = [s for s in signins if (s.get("status") or {}).get("errorCode") == 0]

    known_countries = set(tenant.known_countries or [])
    is_first_run = len(known_countries) == 0 and tenant.last_signin_check is None

    if is_first_run:
        # Primera ejecución — establece la línea base de países conocidos sin alertar
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
    from collections import defaultdict
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

    # Guardar anomalías y actualizar baseline/checkpoint
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

    from django.conf import settings
    from emailmon.services import send_tracked_email

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
        from core.models import SignInAnomalyEvent
        SignInAnomalyEvent.objects.filter(
            id__in=[a.id for a in anomalies]
        ).update(notified=True)
        logger.info(f"Alerta de sign-in enviada para {client} "
                    f"({len(anomalies)} anomalías) → {recipients}")
    except Exception as e:
        logger.error(f"Error enviando alerta de sign-in para {client}: {e}")
