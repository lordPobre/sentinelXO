"""
Sentinel XO — Reporte PDF de Postura de Seguridad
=================================================
Reconstruido sobre `reports.pdf_theme`.

- `build_security_report_pdf(client)` → datos reales (Django).
- `compose_security_story(data)` → presentación pura (sin Django).
"""
import io

from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Spacer, PageBreak, Table, TableStyle

from reports import pdf_theme as T


# ── Mapas ────────────────────────────────────────────────────────────────────
_RISK = {"bajo": ("green", T.GREEN), "medio": ("amber", T.AMBER),
         "alto": ("red", T.RED), "critico": ("red", T.RED)}
_SEV = {"info": "blue", "warning": "amber", "critical": "red", "ok": "green"}
_SEV_LBL = {"info": "Info", "warning": "Advert.", "critical": "Crítico", "ok": "OK"}
_PRI_LBL = {"baja": "Baja", "media": "Media", "alta": "Alta", "critica": "Crítica"}


def _risk_banner(text, nivel):
    """Caja de resumen con franja de acento y pill de riesgo por nivel."""
    kind, accent = _RISK.get(nivel, ("blue", T.BRAND))
    tint = {"green": T.colors.HexColor("#EDF9F4"), "amber": T.colors.HexColor("#FFF7EA"),
            "red": T.colors.HexColor("#FDEFEF"), "blue": T.colors.HexColor("#F1F6FF")}[kind]
    left = T.Paragraph(text, T.ps("rb", fontName=T.FONT, fontSize=9.5, textColor=T.BODY, leading=14.5))
    right = T.pill(f"Riesgo {nivel}" if nivel else "Sin análisis", kind)
    box = Table([[left, right]], colWidths=[T.CW * 0.78, T.CW * 0.22])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), tint),
        ("LEFTPADDING", (0, 0), (-1, -1), 15), ("RIGHTPADDING", (0, 0), (-1, -1), 15),
        ("TOPPADDING", (0, 0), (-1, -1), 13), ("BOTTOMPADDING", (0, 0), (-1, -1), 13),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, accent),
    ]))
    return box


# ════════════════════════════════════════════════════════════════════════════
#  COMPOSICIÓN (pura)
# ════════════════════════════════════════════════════════════════════════════
def compose_security_story(d: dict) -> list:
    story = []
    ai = d.get("ai")

    story += T.header_band(d["company"], "Reporte de Postura de Seguridad", d["generated_date"])

    story.append(T.info_strip([
        ("Cliente",         d["client_name"], True),
        ("Contacto",        d["client_email"]),
        ("Nivel de riesgo", d["risk_label"]),
        ("Generado",        d["generated_at"]),
    ]))
    story.append(T.gap(20))

    # ── Resumen ejecutivo ────────────────────────────────────────────────────
    story += T.section("Resumen Ejecutivo", "Análisis general de la postura de seguridad")
    if ai:
        story.append(_risk_banner(ai.get("resumen", ""), ai.get("nivel_riesgo")))
    else:
        story.append(T.callout("Sin análisis IA",
            "No se ha generado un análisis de seguridad con IA para este cliente todavía.",
            accent=T.MUTED, tint=T.SUBTLE))
    story.append(T.gap(18))

    # ── Indicadores M365 ─────────────────────────────────────────────────────
    story += T.section("Indicadores M365",
                       "Microsoft Secure Score y cobertura de autenticación multifactor")
    m = d.get("m365")
    if m:
        rows = [[T.th("Indicador"), T.th("Valor", TA_RIGHT), T.th("Progreso"), T.th("", TA_CENTER)]]
        # Secure Score
        if m["secure_score"] is not None:
            pct = m["secure_score_pct"]
            rows.append([
                T.td("Microsoft Secure Score", bold=True, size=9.5),
                T.td(f'{m["secure_score"]:.0f} / {m["secure_score_max"]:.0f}', size=9.5, align=TA_RIGHT, mono=True),
                T.progress(pct, (T.GREEN if (pct or 0) >= 70 else (T.AMBER if (pct or 0) >= 40 else T.RED)), width=150, show_label=False),
                T.pill(f"{pct:.0f}%" if pct is not None else "—",
                       "green" if (pct or 0) >= 70 else ("amber" if (pct or 0) >= 40 else "red")),
            ])
        else:
            rows.append([T.td("Microsoft Secure Score", bold=True, size=9.5),
                         T.td("Sin datos", size=9, color=T.MUTED), "", ""])
        # MFA
        if m["mfa_total"] is not None:
            pct = m["mfa_pct"]
            rows.append([
                T.td("Cobertura MFA", bold=True, size=9.5),
                T.td(f'{m["mfa_registered"]} / {m["mfa_total"]} usuarios', size=9.5, align=TA_RIGHT, mono=True),
                T.progress(pct, (T.GREEN if (pct or 0) >= 90 else (T.AMBER if (pct or 0) >= 50 else T.RED)), width=150, show_label=False),
                T.pill(f"{pct:.0f}%" if pct is not None else "—",
                       "green" if (pct or 0) >= 90 else ("amber" if (pct or 0) >= 50 else "red")),
            ])
        else:
            rows.append([T.td("Cobertura MFA", bold=True, size=9.5),
                         T.td("Sin datos", size=9, color=T.MUTED), "", ""])
        story.append(T.table(rows,
            col_widths=[T.CW*0.34, T.CW*0.26, T.CW*0.27, T.CW*0.13],
            aligns={2: "C", 3: "C"}))
        if m.get("no_mfa_users"):
            extra = f" y {len(m['no_mfa_users']) - 10} más..." if len(m["no_mfa_users"]) > 10 else ""
            story.append(T.gap(8))
            story.append(T.P("<b>Usuarios sin MFA registrado:</b> " + ", ".join(m["no_mfa_users"][:10]) + extra,
                             fontName=T.FONT, fontSize=8.5, textColor=T.MUTED, leading=12))
        if m.get("last_check"):
            story.append(T.gap(6))
            story.append(T.P(f"Última verificación: {m['last_check']}",
                             fontName=T.MONO, fontSize=7.5, textColor=T.FAINT))
    else:
        story.append(T.empty("No se ha ejecutado ninguna verificación de seguridad M365 para este cliente."))
    story.append(T.gap(18))

    # ── Certificados SSL ─────────────────────────────────────────────────────
    story += T.section("Certificados SSL", "Estado de los certificados de dominios monitoreados")
    doms = d["domains"]
    if doms:
        rows = [[T.th("Dominio"), T.th("Estado", TA_CENTER), T.th("Vence", TA_CENTER),
                 T.th("Días", TA_CENTER), T.th("Emisor")]]
        for x in doms:
            rows.append([
                T.td(x["fqdn"], bold=True),
                T.pill(x["ssl_label"], x["ssl_kind"]),
                T.td(x["ssl_expiry"] or "—", align=TA_CENTER, mono=True, size=8),
                T.td(x["ssl_days"] if x["ssl_days"] is not None else "—", align=TA_CENTER, mono=True),
                T.td(x["ssl_issuer"] or "—", size=8, color=T.MUTED),
            ])
        story.append(T.table(rows,
            col_widths=[T.CW*0.28, T.CW*0.16, T.CW*0.16, T.CW*0.10, T.CW*0.30],
            aligns={1: "C", 2: "C", 3: "C"}))
    else:
        story.append(T.empty("Este cliente no tiene dominios configurados."))
    story.append(T.gap(18))

    # ── Hallazgos IA ─────────────────────────────────────────────────────────
    if ai and (ai.get("hallazgos") or ai.get("recomendaciones")):
        story += T.section("Hallazgos del Análisis IA", "Observaciones detectadas en la última evaluación")
        if ai.get("hallazgos"):
            rows = [[T.th("Hallazgo"), T.th("Descripción"), T.th("Severidad", TA_CENTER)]]
            for h in ai["hallazgos"]:
                rows.append([
                    T.td(h.get("titulo", ""), bold=True),
                    T.td(h.get("detalle", ""), size=8, color=T.MUTED),
                    T.pill(_SEV_LBL.get(h.get("severidad"), "Info"), _SEV.get(h.get("severidad"), "blue")),
                ])
            story.append(T.table(rows,
                col_widths=[T.CW*0.28, T.CW*0.55, T.CW*0.17], aligns={2: "C"}))
            story.append(T.gap(12))
        if ai.get("recomendaciones"):
            story.append(T.P("RECOMENDACIONES", fontName=T.FONT_SB, fontSize=9.5,
                             textColor=T.TEXT, leading=13))
            story.append(T.gap(6))
            rows = [[T.th("Acción"), T.th("Impacto"), T.th("Prioridad", TA_CENTER)]]
            for r in ai["recomendaciones"]:
                pri = r.get("prioridad")
                kind = "red" if pri in ("alta", "critica") else ("amber" if pri == "media" else "slate")
                rows.append([
                    T.td(r.get("accion", ""), bold=True, size=8.5),
                    T.td(r.get("impacto", ""), size=8, color=T.MUTED),
                    T.pill(_PRI_LBL.get(pri, "Media"), kind),
                ])
            story.append(T.table(rows,
                col_widths=[T.CW*0.42, T.CW*0.41, T.CW*0.17], aligns={2: "C"}))
        story.append(T.gap(18))

    # ── Anomalías de seguridad (agente) ──────────────────────────────────────
    story.append(PageBreak())
    story += T.section("Anomalías de Seguridad Detectadas",
                       "Cambios identificados por el agente (administradores, inicio, tareas programadas)")
    an = d["anomalies"]
    if an:
        rows = [[T.th("Fecha"), T.th("Equipo"), T.th("Tipo"), T.th("Detalle"), T.th("Estado", TA_CENTER)]]
        for a in an:
            estado = T.pill("Revisada", "green") if a["status"] == "acknowledged" \
                else T.pill(_SEV_LBL.get(a["severity"], "Info"), _SEV.get(a["severity"], "blue"))
            rows.append([
                T.td(a["date"], size=8, mono=True),
                T.td(a["device"], size=8),
                T.td(a["type"], size=8),
                T.td(a["summary"], size=8, color=T.MUTED),
                estado,
            ])
        story.append(T.table(rows,
            col_widths=[T.CW*0.15, T.CW*0.18, T.CW*0.16, T.CW*0.31, T.CW*0.20], aligns={4: "C"}))
        story.append(T.gap(8))
        story.append(T.P(f"<b>{d['anomalies_open']}</b> anomalía(s) sin revisar de un total de "
                         f"<b>{d['anomalies_total']}</b> registradas (últimas 50).",
                         fontName=T.FONT, fontSize=8.5, textColor=T.MUTED))
    else:
        story.append(T.empty("No se han detectado anomalías de seguridad en los dispositivos de este cliente."))

    # ── Inicios de sesión sospechosos ────────────────────────────────────────
    sg = d["signin"]
    if sg:
        story.append(T.gap(18))
        story += T.section("Inicios de Sesión Sospechosos (M365)",
                           "Países nuevos, viaje imposible y sign-ins riesgosos detectados")
        rows = [[T.th("Fecha"), T.th("Tipo"), T.th("Detalle"), T.th("Estado", TA_CENTER)]]
        for a in sg:
            estado = T.pill("Revisada", "green") if a["status"] == "acknowledged" \
                else T.pill(_SEV_LBL.get(a["severity"], "Info"), _SEV.get(a["severity"], "blue"))
            rows.append([
                T.td(a["date"], size=8, mono=True),
                T.td(a["type"], size=8),
                T.td(a["summary"], size=8, color=T.MUTED),
                estado,
            ])
        story.append(T.table(rows,
            col_widths=[T.CW*0.15, T.CW*0.20, T.CW*0.45, T.CW*0.20], aligns={3: "C"}))
        story.append(T.gap(8))
        story.append(T.P(f"<b>{d['signin_open']}</b> anomalía(s) sin revisar de un total de "
                         f"<b>{d['signin_total']}</b> registradas (últimas 50).",
                         fontName=T.FONT, fontSize=8.5, textColor=T.MUTED))

    # ── Conectividad de agentes ──────────────────────────────────────────────
    devs = d["devices"]
    if devs:
        story.append(T.gap(18))
        story += T.section("Conectividad de Agentes", "Estado de los equipos monitoreados por Sentinel XO")
        rows = [[T.th("Equipo"), T.th("Tipo"), T.th("Estado", TA_CENTER), T.th("Último contacto", TA_CENTER)]]
        for x in devs:
            rows.append([
                T.td(x["name"], bold=True),
                T.td(x["type"], size=8, color=T.MUTED),
                T.pill(x["status_label"], x["status_kind"]),
                T.td(x["last_seen"], size=8, color=T.MUTED, align=TA_CENTER, mono=True),
            ])
        story.append(T.table(rows,
            col_widths=[T.CW*0.32, T.CW*0.20, T.CW*0.20, T.CW*0.28], aligns={2: "C", 3: "C"}))

    # ── Inventario de software + CVE ─────────────────────────────────────────
    sw = d["software"]
    if sw:
        story.append(PageBreak())
        story += T.section("Inventario de Software y Vulnerabilidades",
                           "Análisis de CVEs por equipo basado en conocimiento del modelo (IA)")
        for snap in sw:
            head = Table([[
                T.P(f'<b>{snap["device"]}</b>', fontName=T.FONT_SB, fontSize=10.5, textColor=T.TEXT, leading=14),
                T.P(f'{snap["n_software"]} programas instalados', fontName=T.FONT, fontSize=8.5,
                    textColor=T.MUTED, leading=12, alignment=TA_RIGHT),
            ]], colWidths=[T.CW * 0.7, T.CW * 0.3])
            head.setStyle(TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.75, T.LINE),
            ]))
            story.append(head)
            story.append(T.gap(8))

            cve = snap["cve"]
            if not cve:
                story.append(T.empty("Análisis de vulnerabilidades (CVE) aún no generado para este equipo."))
                story.append(T.gap(14))
                continue

            story.append(_risk_banner(cve.get("resumen", ""), cve.get("nivel_riesgo")))
            story.append(T.gap(8))

            if cve.get("hallazgos"):
                rows = [[T.th("Software"), T.th("Detalle"), T.th("Severidad", TA_CENTER)]]
                for h in cve["hallazgos"]:
                    rows.append([
                        T.td(h.get("software", ""), bold=True, size=8.5),
                        T.td(h.get("detalle", ""), size=8, color=T.MUTED),
                        T.pill(_SEV_LBL.get(h.get("severidad"), "Info"), _SEV.get(h.get("severidad"), "blue")),
                    ])
                story.append(T.table(rows,
                    col_widths=[T.CW*0.30, T.CW*0.53, T.CW*0.17], aligns={2: "C"}))
            else:
                story.append(T.empty("No se detectó software con vulnerabilidades conocidas relevantes."))

            if cve.get("recomendaciones"):
                story.append(T.gap(6))
                for r in cve["recomendaciones"]:
                    story.append(T.P(
                        f'<b>{r.get("accion", "")}</b>  <font color="#6B7688">'
                        f'({_PRI_LBL.get(r.get("prioridad"), "Media")})</font>',
                        fontName=T.FONT, fontSize=8.5, textColor=T.TEXT, leading=13))

            if snap.get("checked"):
                story.append(T.gap(4))
                story.append(T.P(f'Análisis generado: {snap["checked"]}',
                                 fontName=T.MONO, fontSize=7.5, textColor=T.FAINT))
            story.append(T.gap(14))

    return story


def _render(data: dict) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=T.ML, rightMargin=T.MR,
                            topMargin=T.MT, bottomMargin=T.MB)
    footer = T.make_footer(data["company"], data["support"])
    doc.build(compose_security_story(data), onFirstPage=footer, onLaterPages=footer)
    pdf = buf.getvalue()
    buf.close()
    return pdf


# ════════════════════════════════════════════════════════════════════════════
#  ENTRADA CON DATOS REALES (Django)
# ════════════════════════════════════════════════════════════════════════════
def _ssl_view(d):
    if d.ssl_error:
        return ("Error", "red", "", None, (d.ssl_error[:40] if d.ssl_error else "—"))
    if d.ssl_status == "ok":
        return ("OK", "green",
                d.ssl_expiry_date.strftime("%d/%m/%Y") if d.ssl_expiry_date else "",
                d.days_until_ssl_expiry, d.ssl_issuer or "—")
    if d.ssl_status in ("warning", "critical", "expired"):
        kind = "red" if d.ssl_status in ("critical", "expired") else "amber"
        return (d.get_ssl_status_display(), kind,
                d.ssl_expiry_date.strftime("%d/%m/%Y") if d.ssl_expiry_date else "",
                d.days_until_ssl_expiry, d.ssl_issuer or "—")
    return ("Desconocido", "slate", "", None, "—")


def build_security_report_pdf(client) -> bytes:
    from django.conf import settings
    from django.utils import timezone
    from core.models import (SecurityCheck, SecurityAnomalyEvent, SignInAnomalyEvent,
                             HardwareDevice, SoftwareSnapshot)

    company = getattr(settings, "SENTINEL_COMPANY_NAME", "Sentinel XO")
    now = timezone.localtime(timezone.now())

    latest = SecurityCheck.objects.filter(client=client).order_by("-checked_at").first()
    ai = latest.ai_summary if (latest and latest.ai_summary) else None

    domains = list(client.domains.all())
    anomalies = list(SecurityAnomalyEvent.objects.filter(device__client=client)
                     .select_related("device").order_by("-detected_at")[:50])
    signin = list(SignInAnomalyEvent.objects.filter(client=client).order_by("-detected_at")[:50])
    devices = list(HardwareDevice.objects.filter(client=client, is_active=True))
    software = list(SoftwareSnapshot.objects.filter(device__client=client, device__is_active=True)
                    .select_related("device"))

    risk_label = (ai.get("nivel_riesgo", "—").upper() if ai else "SIN ANÁLISIS")

    m365 = None
    if latest:
        no_mfa = (latest.check_details or {}).get("mfa", {}).get("no_mfa_users") or []
        m365 = {
            "secure_score": latest.secure_score,
            "secure_score_max": latest.secure_score_max,
            "secure_score_pct": latest.secure_score_percent,
            "mfa_total": latest.mfa_total,
            "mfa_registered": latest.mfa_registered,
            "mfa_pct": latest.mfa_percent,
            "no_mfa_users": no_mfa,
            "last_check": timezone.localtime(latest.checked_at).strftime("%d/%m/%Y %H:%M"),
        }

    def dom_view(d):
        label, kind, expiry, days, issuer = _ssl_view(d)
        return {"fqdn": d.fqdn, "ssl_label": label, "ssl_kind": kind,
                "ssl_expiry": expiry, "ssl_days": days, "ssl_issuer": issuer}

    def anom_view(a):
        return {"date": timezone.localtime(a.detected_at).strftime("%d/%m/%Y %H:%M"),
                "device": a.device.display_name, "type": a.get_anomaly_type_display(),
                "summary": a.detail_summary, "status": a.status, "severity": a.severity}

    def signin_view(a):
        return {"date": timezone.localtime(a.detected_at).strftime("%d/%m/%Y %H:%M"),
                "type": a.get_anomaly_type_display(), "summary": a.detail_summary,
                "status": a.status, "severity": a.severity}

    def dev_view(dv):
        if dv.is_online:
            lbl, kind = "En línea", "green"
        elif getattr(dv, "is_offline", False):
            lbl, kind = "Sin conexión", "red"
        else:
            lbl, kind = "Sin datos", "slate"
        return {"name": dv.display_name, "type": dv.get_device_type_display(),
                "status_label": lbl, "status_kind": kind,
                "last_seen": timezone.localtime(dv.last_seen).strftime("%d/%m/%Y %H:%M") if dv.last_seen else "—"}

    def sw_view(snap):
        cve = snap.cve_analysis
        return {"device": snap.device.display_name,
                "n_software": len(snap.software_list or []),
                "cve": cve,
                "checked": (timezone.localtime(snap.cve_checked_at).strftime("%d/%m/%Y %H:%M")
                            if snap.cve_checked_at else "")}

    data = {
        "company": company,
        "support": getattr(settings, "SENTINEL_SUPPORT_EMAIL", "soporte@perseustechnology.dev"),
        "generated_date": now.strftime("%d/%m/%Y"),
        "generated_at": now.strftime("%d/%m/%Y %H:%M"),
        "client_name": client.company_name,
        "client_email": client.contact_email,
        "risk_label": risk_label,
        "ai": ai,
        "m365": m365,
        "domains": [dom_view(x) for x in domains],
        "anomalies": [anom_view(a) for a in anomalies],
        "anomalies_open": sum(1 for a in anomalies if a.status == "open"),
        "anomalies_total": len(anomalies),
        "signin": [signin_view(a) for a in signin],
        "signin_open": sum(1 for a in signin if a.status == "open"),
        "signin_total": len(signin),
        "devices": [dev_view(x) for x in devices],
        "software": [sw_view(x) for x in software],
    }
    return _render(data)
