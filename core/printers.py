# ═══════════════════════════════════════════════════════════════════════════
#  core/printers.py — Fase 2 combinada (REEMPLAZA la versión anterior)
#  Procesa impresoras de RED (SNMP por IP) y LOCALES/USB (WMI por nombre).
#  Auto-registra las que descubre, con dedup: si una local trae IP que ya es
#  una impresora de red, se omite (gana la de red, que trae más datos).
# ═══════════════════════════════════════════════════════════════════════════
import logging
from django.utils import timezone

logger = logging.getLogger("perseus")

LOW_WARN = 15
LOW_CRIT = 5
_CRIT_ERRORS = {"noToner", "noPaper", "jammed", "doorOpen",
                "markerSupplyMissing", "serviceRequested", "offline"}
_WARN_ERRORS = {"lowToner", "lowPaper", "outputNearFull", "outputFull",
                "inputTrayEmpty", "overduePreventMaint"}


def _compute_risk(supplies, errors):
    reasons, level = [], "ok"
    errs = set(errors or [])
    crit = errs & _CRIT_ERRORS
    if crit:
        level = "critical"
        reasons += [f"Error: {e}" for e in sorted(crit)]
    lowest = None
    for s in supplies or []:
        p = s.get("level_percent")
        if p is not None:
            lowest = p if lowest is None else min(lowest, p)
    if lowest is not None:
        if lowest < LOW_CRIT:
            level = "critical"; reasons.append(f"Consumible al {lowest}%")
        elif lowest < LOW_WARN and level != "critical":
            level = "warning"; reasons.append(f"Consumible al {lowest}%")
    if level == "ok":
        warn = errs & _WARN_ERRORS
        if warn:
            level = "warning"; reasons += [f"Aviso: {e}" for e in sorted(warn)]
    return level, reasons


def _save_snapshot(device, st, source):
    from core.models import PrinterSnapshot
    supplies = st.get("supplies") or []
    errors = st.get("error_states") or []
    level, reasons = _compute_risk(supplies, errors)
    PrinterSnapshot.objects.update_or_create(
        device=device,
        defaults={
            "source": source,
            "model_description": (st.get("model_description") or "")[:255],
            "device_status": (st.get("device_status") or "")[:32],
            "status_label": (st.get("status_label") or "")[:120],
            "error_states": errors,
            "supplies": supplies,
            "page_count": st.get("page_count"),
            "risk_level": level,
            "risk_reasons": reasons,
        },
    )


def process_printer_status(client, probes):
    """
    'probes' = lista de items {source, ip, name, host, online, status}.
      source="snmp" → impresora de red (status con supplies/tóner)
      source="wmi"  → impresora local/USB (status sin supplies, solo estado)
    Auto-registra impresoras nuevas. Devuelve cantidad marcada en línea.
    """
    from core.models import HardwareDevice
    now = timezone.now()
    online_count = 0

    # IPs de red ya conocidas (para dedup de las locales compartidas)
    known_net_ips = set(
        HardwareDevice.objects.filter(client=client, device_type="printer", is_active=True)
        .exclude(ip_address__isnull=True)
        .values_list("ip_address", flat=True)
    )

    # Procesar primero las de red (snmp) para que el dedup funcione
    items = sorted(
        [p for p in (probes or []) if isinstance(p, dict)],
        key=lambda p: 0 if p.get("source", "snmp") == "snmp" else 1,
    )

    for p in items:
        source = p.get("source", "snmp")
        st = p.get("status") or {}
        online = bool(p.get("online"))

        if source == "snmp":
            ip = p.get("ip")
            if not ip:
                continue
            device = HardwareDevice.objects.filter(
                client=client, device_type="printer", ip_address=ip
            ).first()
            if not device:
                # Solo auto-registramos si SNMP respondió (confirma que es impresora).
                # Si solo respondió el puerto TCP pero sin SNMP, no creamos a ciegas.
                if not st:
                    continue
                name = (st.get("model_description") or f"Impresora {ip}")[:60]
                device = HardwareDevice.objects.create(
                    client=client, device_type="printer", ip_address=ip,
                    hostname=f"net:{ip}", friendly_name=name, is_active=True,
                )
                known_net_ips.add(ip)
                logger.info(f"Impresora de red auto-registrada: {name} ({ip}) / {client}")
            if online:
                device.last_seen = now
                device.save(update_fields=["last_seen"])
                online_count += 1
            if st:
                _save_snapshot(device, st, "snmp")

        else:  # wmi (local/USB)
            name = p.get("name")
            if not name:
                continue
            ip = p.get("ip")
            if ip and ip in known_net_ips:
                continue  # dedup: ya está como impresora de red
            host = p.get("host") or "local"
            key = f"wmi:{host}:{name}"[:255]
            device = HardwareDevice.objects.filter(
                client=client, device_type="printer", hostname=key
            ).first()
            if not device:
                device = HardwareDevice.objects.create(
                    client=client, device_type="printer",
                    hostname=key, friendly_name=name[:60],
                    ip_address=(ip or None), is_active=True,
                )
                logger.info(f"Impresora local auto-registrada: {name} @ {host} / {client}")
            if online:
                device.last_seen = now
                device.save(update_fields=["last_seen"])
                online_count += 1
            _save_snapshot(device, st, "wmi")

    return online_count
