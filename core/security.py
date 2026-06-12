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
