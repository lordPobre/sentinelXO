"""
Sentinel XO — Score de Seguridad por cliente
============================================
Motor determinístico (sin IA) que combina señales ya capturadas en los modelos
y produce un puntaje 0–100, una letra A–F, color, desglose por dimensión y
hallazgos. Las dimensiones sin datos NO penalizan: el puntaje se normaliza
sobre las dimensiones aplicables.

Pesos (sobre 100):
  MFA 20 · Secure Score 15 · Anomalías 20 · Red 15 · CVE 15 · Reportando 10 · Dominios/SSL 5
"""
import logging
from django.utils import timezone
from core.models import (Client, SecurityAnomalyEvent, SecurityScoreSnapshot)

logger = logging.getLogger("perseus")


def _dim(key, label, maximo, earned, applicable, detail):
    earned = max(0.0, min(float(earned), float(maximo)))
    pct = round(100 * earned / maximo) if (applicable and maximo) else 0
    return {"key": key, "label": label, "max": maximo,
            "earned": round(earned, 1), "pct": pct,
            "applicable": applicable, "detail": detail}


def _grade(score):
    if score >= 90: return "A", "#10b981", "Excelente"
    if score >= 80: return "B", "#22e6ff", "Bueno"
    if score >= 70: return "C", "#e0930b", "Aceptable"
    if score >= 60: return "D", "#f59e0b", "Mejorable"
    return "F", "#ef4444", "Crítico"


def grade_color(grade):
    return {"A": "#10b981", "B": "#22e6ff", "C": "#e0930b",
            "D": "#f59e0b", "F": "#ef4444"}.get(grade, "#64748b")


def compute_security_score(client) -> dict:
    devices   = list(client.devices.filter(is_active=True))
    total_dev = len(devices)
    dims = []
    findings = []

    sc = client.security_checks.first()  

    if sc and sc.mfa_percent is not None:
        pct = sc.mfa_percent
        if pct < 90:
            findings.append(f"Cobertura MFA en {pct:.0f}% (objetivo ≥90%)")
        dims.append(_dim("mfa", "Cobertura MFA", 20, 20 * pct / 100, True, f"{pct:.0f}% con MFA"))
    else:
        dims.append(_dim("mfa", "Cobertura MFA", 20, 0, False, "Sin datos M365"))

    if sc and sc.secure_score_percent is not None:
        pct = sc.secure_score_percent
        if pct < 60:
            findings.append(f"Secure Score M365 bajo ({pct:.0f}%)")
        dims.append(_dim("secure", "Secure Score M365", 15, 15 * pct / 100, True, f"{pct:.0f}%"))
    else:
        dims.append(_dim("secure", "Secure Score M365", 15, 0, False, "Sin datos M365"))

    anoms = SecurityAnomalyEvent.objects.filter(device__client=client, status="open")
    crit = anoms.filter(severity="critical").count()
    warn = anoms.filter(severity="warning").count()
    info = anoms.filter(severity="info").count()
    pen = crit * 8 + warn * 3 + info * 1
    if crit:
        findings.append(f"{crit} anomalía(s) de seguridad crítica(s) abierta(s)")
    elif warn:
        findings.append(f"{warn} anomalía(s) de seguridad abierta(s)")
    detail = "Sin anomalías abiertas" if (crit + warn + info) == 0 else f"{crit} crít · {warn} adv · {info} info"
    dims.append(_dim("anomalies", "Anomalías de seguridad", 20, 20 - pen, True, detail))

    nets = [getattr(d, "network_snapshot", None) for d in devices]
    nets = [n for n in nets if n]
    if nets:
        pen = 0
        issues = []
        for n in nets:
            if n.firewall_all_on is False:
                pen += 4; issues.append(f"{n.device.display_name}: firewall parcial/apagado")
            if n.is_open_wifi:
                pen += 4; issues.append(f"{n.device.display_name}: WiFi abierta")
            if n.risk_level == "critical":
                pen += 4
            elif n.risk_level == "warning":
                pen += 2
        findings += issues[:3]
        detail = "Sin problemas de red" if pen == 0 else f"{len(issues)} problema(s) de red"
        dims.append(_dim("network", "Postura de red", 15, 15 - pen, True, detail))
    else:
        dims.append(_dim("network", "Postura de red", 15, 0, False, "Sin datos de red"))

    sws = [getattr(d, "software_snapshot", None) for d in devices]
    sws = [s for s in sws if s and s.cve_analysis]
    if sws:
        pen = 0
        for s in sws:
            nivel = (s.cve_analysis or {}).get("nivel_riesgo")
            if nivel == "critico":
                pen += 6; findings.append(f"{s.device.display_name}: vulnerabilidades de riesgo crítico")
            elif nivel == "alto":
                pen += 3
            elif nivel == "medio":
                pen += 1
        detail = "Sin vulnerabilidades relevantes" if pen == 0 else "Vulnerabilidades detectadas"
        dims.append(_dim("cve", "Vulnerabilidades (CVE)", 15, 15 - pen, True, detail))
    else:
        dims.append(_dim("cve", "Vulnerabilidades (CVE)", 15, 0, False, "Sin análisis CVE"))

    if total_dev:
        online = sum(1 for d in devices if d.is_online)
        if online < total_dev:
            findings.append(f"{total_dev - online} equipo(s) sin reportar")
        dims.append(_dim("reporting", "Equipos reportando", 10, 10 * online / total_dev, True,
                         f"{online}/{total_dev} en línea"))
    else:
        dims.append(_dim("reporting", "Equipos reportando", 10, 0, False, "Sin equipos"))

    domains = list(client.domains.all())
    if domains:
        pen = 0
        for d in domains:
            for days, kind in ((d.days_until_ssl_expiry, "SSL"), (d.days_until_expiry, "dominio")):
                if days is None:
                    continue
                if days < 0:
                    pen += 2.5; findings.append(f"{d.fqdn}: {kind} vencido")
                elif days < 15:
                    pen += 1.5
                elif days < 30:
                    pen += 0.5
        detail = "Certificados/dominios al día" if pen == 0 else "Vencimientos próximos"
        dims.append(_dim("domains", "Dominios y SSL", 5, 5 - pen, True, detail))
    else:
        dims.append(_dim("domains", "Dominios y SSL", 5, 0, False, "Sin dominios"))

    applicable = [d for d in dims if d["applicable"]]
    max_sum    = sum(d["max"] for d in applicable) or 1
    earned_sum = sum(d["earned"] for d in applicable)
    score = round(100 * earned_sum / max_sum)
    grade, color, label = _grade(score)

    return {
        "score": score,
        "grade": grade,
        "color": color,
        "label": label,
        "breakdown": applicable,
        "findings": findings[:6],
        "computed_at": timezone.now().isoformat(),
    }


# ── Histórico y tendencia ───────────────────────────────────────────────────

def snapshot_security_score(client) -> dict:
    """Calcula y persiste el score (para tendencia)."""
    r = compute_security_score(client)
    SecurityScoreSnapshot.objects.create(
        client=client, score=r["score"], grade=r["grade"],
        breakdown=r["breakdown"], findings=r["findings"],
    )
    return r


def get_score_delta(client, current_score):
    """Diferencia vs el snapshot de ~30 días atrás (o el más antiguo disponible)."""
    ref = (SecurityScoreSnapshot.objects
           .filter(client=client, computed_at__lte=timezone.now() - timezone.timedelta(days=25))
           .order_by("-computed_at").first())
    if not ref:
        ref = (SecurityScoreSnapshot.objects
               .filter(client=client).order_by("computed_at").first())
    if not ref:
        return None
    return current_score - ref.score
