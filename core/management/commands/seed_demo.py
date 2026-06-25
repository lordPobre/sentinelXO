"""
seed_demo — Datos de demostración para Sentinel XO
==================================================
Crea DOS clientes ficticios para demos/ventas, claramente identificables y
borrables sin tocar datos reales:

  • "Comercial Aurora SpA"  → SANO (todo verde, score A)
  • "Logística Andes Ltda"  → CON PROBLEMAS (disco llenándose, equipo offline,
                               anomalía crítica, SSL por vencer, score más bajo)

Ambos llevan rut con prefijo "DEMO-" y la marca [SEED_DEMO] en notas, así el
--wipe borra SOLO lo demo.

Uso:
  python manage.py seed_demo            # crea (aborta si ya existe)
  python manage.py seed_demo --reset    # borra lo demo y lo vuelve a crear
  python manage.py seed_demo --wipe     # solo borra lo demo
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import (
    Client, HardwareDevice, TelemetrySnapshot, Domain,
    M365Tenant, M365License, MaintenanceIncident,
    SecurityCheck, SecuritySnapshot, SecurityAnomalyEvent,
    SoftwareSnapshot, NetworkSnapshot, SecurityScoreSnapshot,
    AlertRule, AlertEvent,
)

DEMO_RUT_PREFIX = "DEMO-"
DEMO_MARK = "[SEED_DEMO]"
HOUR = 3600


class Command(BaseCommand):
    help = "Crea/borra dos clientes demo (sano + con problemas) con 14 días de telemetría."

    def add_arguments(self, parser):
        parser.add_argument("--wipe", action="store_true", help="Borra solo los datos demo.")
        parser.add_argument("--reset", action="store_true", help="Borra lo demo y lo recrea.")

    # ── entrypoint ───────────────────────────────────────────────────────────
    def handle(self, *args, **opts):
        random.seed(42)
        if opts["wipe"] or opts["reset"]:
            self._wipe()
            if opts["wipe"]:
                return
        if Client.objects.filter(rut__startswith=DEMO_RUT_PREFIX).exists():
            self.stdout.write(self.style.WARNING(
                "Ya existen datos demo. Usa --reset para recrear o --wipe para borrar."))
            return
        self._build_healthy()
        self._build_problem()
        self.stdout.write(self.style.SUCCESS("✓ Datos demo creados (2 clientes). Usa --wipe para borrarlos."))

    # ── wipe seguro ──────────────────────────────────────────────────────────
    def _wipe(self):
        qs = Client.objects.filter(rut__startswith=DEMO_RUT_PREFIX)
        n = qs.count()
        qs.delete()  # cascada: devices, snapshots, incidentes, dominios, m365, scores, alertas
        self.stdout.write(self.style.SUCCESS(f"✓ {n} cliente(s) demo borrado(s)."))

    # ── helpers de creación ──────────────────────────────────────────────────
    def _client(self, name, rut, plan, email):
        return Client.objects.create(
            company_name=name, rut=rut, plan=plan,
            contact_name="Equipo TI", contact_email=email,
            contact_phone="+56 2 2345 6789",
            notes=f"{DEMO_MARK} Cliente de demostración generado por seed_demo.",
            is_active=True,
        )

    def _device(self, client, hostname, friendly, dtype, os_name, online=True):
        d = HardwareDevice.objects.create(
            client=client, hostname=hostname, friendly_name=friendly,
            device_type=dtype, os=os_name, os_version="10.0.19045",
            ip_address=f"192.168.1.{random.randint(10, 240)}",
            is_active=True,
        )
        return d

    def _telemetry(self, device, *, days=14, online=True,
                   cpu_base=30, ram_base=50, ram_total=16,
                   disk_total=512, disk_base=55, disk_slope=0.0, ram_slope=0.0,
                   second_disk=None):
        """Genera telemetría horaria. disk_slope/ram_slope en %/día (tendencia)."""
        now = timezone.now()
        # si está offline, el último contacto fue hace ~3h (sin datos recientes)
        end = now - timedelta(hours=3) if not online else now
        start = now - timedelta(days=days)
        rows = []
        t = start
        i = 0
        uptime = random.randint(3, 20) * 86400
        while t <= end:
            day = (t - start).total_seconds() / 86400.0
            # variación diaria suave + ruido
            wave = 8 * random.uniform(-1, 1)
            cpu = _clamp(cpu_base + wave + 6 * random.uniform(-1, 1))
            ram = _clamp(ram_base + ram_slope * day + 4 * random.uniform(-1, 1))
            diskC = _clamp(disk_base + disk_slope * day + 1.2 * random.uniform(-1, 1))
            disks = [{"mountpoint": "C:", "used_percent": round(diskC, 1), "total_gb": disk_total}]
            if second_disk is not None:
                dd = _clamp(second_disk + 0.02 * day + random.uniform(-0.5, 0.5))
                disks.append({"mountpoint": "D:", "used_percent": round(dd, 1), "total_gb": 1024})
            rows.append(TelemetrySnapshot(
                device=device, captured_at=t,
                cpu_percent=round(cpu, 1), ram_used_percent=round(ram, 1),
                ram_total_gb=ram_total, disk_usage=disks,
                uptime_seconds=uptime + i * HOUR,
                temperatures=[{"name": "CPU", "current": round(42 + cpu * 0.25, 1)}],
                network={},
            ))
            t += timedelta(hours=1)
            i += 1
        TelemetrySnapshot.objects.bulk_create(rows, batch_size=500)
        last_at = rows[-1].captured_at if rows else end
        HardwareDevice.objects.filter(pk=device.pk).update(last_seen=last_at)
        return last_at

    def _network(self, device, *, firewall_on=True, open_wifi=False, risk="ok"):
        fw = [{"profile": p, "enabled": firewall_on} for p in ("Domain", "Private", "Public")]
        if not firewall_on:
            fw[2]["enabled"] = False
        NetworkSnapshot.objects.create(
            device=device,
            latency_ms=round(random.uniform(6, 28), 1),
            packet_loss_percent=0.0,
            wifi_ssid="OficinaWiFi" if open_wifi else "",
            wifi_encryption="Open" if open_wifi else "",
            network_category="Private", firewall=fw,
            dns_servers=["1.1.1.1", "8.8.8.8"],
            risk_level=risk,
            risk_reasons=(["Firewall parcialmente desactivado"] if not firewall_on else []),
            security_checked_at=timezone.now(),
        )

    def _software(self, device, *, nivel="bajo"):
        sw = [
            {"name": "Google Chrome", "version": "126.0"},
            {"name": "Microsoft 365", "version": "16.0"},
            {"name": "7-Zip", "version": "23.01"},
            {"name": "Adobe Acrobat Reader", "version": "24.002"},
        ]
        cve = {"nivel_riesgo": nivel, "hallazgos": []}
        if nivel in ("alto", "critico"):
            cve["hallazgos"] = [{
                "software": "Adobe Acrobat Reader", "severidad": "alta",
                "detalle": "Versión con vulnerabilidad conocida de ejecución remota.",
                "cves_referencia": ["CVE-2024-30284"],
            }]
        SoftwareSnapshot.objects.create(
            device=device, software_list=sw,
            cve_analysis=cve, cve_checked_at=timezone.now(),
        )

    def _sec_fingerprint(self, device):
        SecuritySnapshot.objects.create(
            device=device,
            local_admins=["Administrador", "soporte.ti"],
            startup_programs=["OneDrive", "Teams"],
            scheduled_tasks=["GoogleUpdate", "OfficeBackgroundTask"],
        )

    def _m365(self, client, *, secure, secure_max, mfa_reg, mfa_total):
        M365Tenant.objects.create(
            client=client, tenant_id="demo-tenant-0000",
            azure_client_id="demo-app-0000", azure_client_secret="demo-secret",
            is_active=True, verify_email=client.contact_email,
            sender_mailbox=client.contact_email, last_synced=timezone.now(),
        )
        for sku, fn, tot, con in [
            ("SPE_E3", "Microsoft 365 E3", 25, mfa_total),
            ("EXCHANGESTANDARD", "Exchange Online (Plan 1)", 10, 6),
        ]:
            M365License.objects.create(
                client=client, sku_part_number=sku, friendly_name=fn,
                total_licenses=tot, consumed_licenses=min(con, tot),
                capability_status="Enabled", last_synced=timezone.now(),
            )
        SecurityCheck.objects.create(
            client=client, secure_score=secure, secure_score_max=secure_max,
            mfa_registered=mfa_reg, mfa_total=mfa_total, check_details={},
        )

    def _domain(self, client, fqdn, *, expiry_days, ssl_days):
        today = timezone.now().date()
        d = Domain.objects.create(
            client=client, fqdn=fqdn, registrar="NIC Chile",
            expiry_date=today + timedelta(days=expiry_days),
            ssl_expiry_date=today + timedelta(days=ssl_days),
            ssl_issuer="Let's Encrypt", ssl_protocol="TLS 1.3",
            last_checked=timezone.now(), resolves_dns=True,
        )
        d.refresh_status(); d.refresh_ssl_status(); d.save()
        return d

    def _incident(self, client, title, sev, cat, *, resolved=False, days_ago=0, device=None):
        inc = MaintenanceIncident.objects.create(
            client=client, device=device, title=title, severity=sev,
            category=cat, description="Incidente de demostración.",
            is_resolved=resolved,
            resolved_at=(timezone.now() - timedelta(days=max(0, days_ago - 1))) if resolved else None,
        )
        if days_ago:
            MaintenanceIncident.objects.filter(pk=inc.pk).update(
                created_at=timezone.now() - timedelta(days=days_ago))
        return inc

    def _score_history(self, client, points):
        """points: lista de (días_atrás, score, grade). Retrofecha computed_at."""
        for days_ago, score, grade in points:
            s = SecurityScoreSnapshot.objects.create(
                client=client, score=score, grade=grade, breakdown=[], findings=[])
            SecurityScoreSnapshot.objects.filter(pk=s.pk).update(
                computed_at=timezone.now() - timedelta(days=days_ago))

    # ── CLIENTE SANO ─────────────────────────────────────────────────────────
    def _build_healthy(self):
        c = self._client("Comercial Aurora SpA", "DEMO-SANO-01", "enterprise",
                          "ti@comercialaurora.cl")
        specs = [
            ("SRV-APP01", "Servidor de Aplicaciones", "server", "Windows Server 2022", 50, 58, 64, 1024, 52),
            ("PC-GERENCIA", "PC Gerencia", "workstation", "Windows 11 Pro", 25, 45, 16, 512, 48),
            ("PC-VENTAS01", "PC Ventas 1", "workstation", "Windows 11 Pro", 30, 50, 16, 512, 55),
            ("PC-CONTA01", "PC Contabilidad", "workstation", "Windows 11 Pro", 28, 48, 16, 512, 60),
            ("NB-GERENTE", "Notebook Gerente", "laptop", "Windows 11 Pro", 22, 42, 16, 512, 44),
        ]
        for host, fn, dt, osn, cpu, ram, rt, dtot, dbase in specs:
            d = self._device(c, host, fn, dt, osn, online=True)
            self._telemetry(d, online=True, cpu_base=cpu, ram_base=ram, ram_total=rt,
                            disk_total=dtot, disk_base=dbase, disk_slope=0.05, ram_slope=0.0,
                            second_disk=(40 if dt == "server" else None))
            self._network(d, firewall_on=True, open_wifi=False, risk="ok")
            self._software(d, nivel="bajo")
            self._sec_fingerprint(d)

        self._m365(c, secure=73, secure_max=80, mfa_reg=24, mfa_total=25)  # 91% / 96%
        self._domain(c, "comercialaurora.cl", expiry_days=320, ssl_days=210)
        self._incident(c, "Actualización de Windows aplicada", "low", "hardware",
                       resolved=True, days_ago=9)
        self._incident(c, "Renovación SSL completada", "low", "domain",
                       resolved=True, days_ago=20)
        # score: tendencia al alza
        self._score_history(c, [(30, 90, "A"), (14, 93, "A")])
        _safe_snapshot(c)

    # ── CLIENTE CON PROBLEMAS ────────────────────────────────────────────────
    def _build_problem(self):
        c = self._client("Logística Andes Ltda", "DEMO-PROB-01", "professional",
                          "soporte@logisticaandes.cl")

        # SRV-DATOS: disco llenándose (tendencia fuerte) → pronóstico crítico
        srv = self._device(c, "SRV-DATOS", "Servidor de Datos", "server",
                           "Windows Server 2019", online=True)
        self._telemetry(srv, online=True, cpu_base=55, ram_base=82, ram_total=32,
                        disk_total=1024, disk_base=74, disk_slope=1.05, ram_slope=0.4,
                        second_disk=58)
        self._network(srv, firewall_on=True, open_wifi=False, risk="ok")
        self._software(srv, nivel="alto")
        self._sec_fingerprint(srv)

        # PC con firewall apagado + WiFi abierta → riesgo de red
        pc = self._device(c, "PC-BODEGA", "PC Bodega", "workstation",
                          "Windows 10 Pro", online=True)
        self._telemetry(pc, online=True, cpu_base=35, ram_base=60, ram_total=8,
                        disk_total=256, disk_base=70, disk_slope=0.3)
        self._network(pc, firewall_on=False, open_wifi=True, risk="warning")
        self._software(pc, nivel="medio")
        self._sec_fingerprint(pc)

        # Notebook OFFLINE
        nb = self._device(c, "NB-DESPACHO", "Notebook Despacho", "laptop",
                          "Windows 11 Pro", online=False)
        self._telemetry(nb, online=False, cpu_base=20, ram_base=45, ram_total=8,
                        disk_total=256, disk_base=62)
        self._network(nb, firewall_on=True, open_wifi=False, risk="ok")
        self._software(nb, nivel="bajo")
        self._sec_fingerprint(nb)

        # equipos sanos de relleno
        for host, fn, cpu, ram in [("PC-ADMIN", "PC Administración", 28, 50),
                                   ("PC-RRHH", "PC Recursos Humanos", 26, 48)]:
            d = self._device(c, host, fn, "workstation", "Windows 11 Pro", online=True)
            self._telemetry(d, online=True, cpu_base=cpu, ram_base=ram, ram_total=16,
                            disk_total=512, disk_base=58, disk_slope=0.06)
            self._network(d, firewall_on=True, open_wifi=False, risk="ok")
            self._software(d, nivel="bajo")
            self._sec_fingerprint(d)

        # Anomalías de seguridad abiertas
        SecurityAnomalyEvent.objects.create(
            device=srv, anomaly_type="new_admin", severity="critical", status="open",
            detail="Nuevo administrador local detectado → usuario 'temp_admin'")
        SecurityAnomalyEvent.objects.create(
            device=pc, anomaly_type="firewall_off", severity="warning", status="open",
            detail="Firewall desactivado en el perfil público")

        # M365 más flojo
        self._m365(c, secure=48, secure_max=80, mfa_reg=14, mfa_total=20)  # 60% / 70%

        # Dominios: uno con SSL por vencer (crítico)
        self._domain(c, "logisticaandes.cl", expiry_days=140, ssl_days=9)
        self._domain(c, "portal-andes.cl", expiry_days=260, ssl_days=180)

        # Incidentes abiertos + histórico
        self._incident(c, "Disco del servidor de datos cerca del límite", "high",
                       "hardware", device=srv)
        self._incident(c, "Equipo de despacho sin conexión", "medium",
                       "connectivity", device=nb)
        self._incident(c, "Bloqueo de cuenta resuelto", "low", "license",
                       resolved=True, days_ago=6)

        # Alertas: reglas + eventos (para el dashboard de alertas)
        r_cpu = AlertRule.objects.create(client=c, metric="cpu", threshold=90,
                                         severity="critical", is_active=True)
        r_ram = AlertRule.objects.create(client=c, metric="ram", threshold=85,
                                         severity="warning", is_active=True)
        AlertRule.objects.create(client=c, metric="cpu_temp", threshold=85,
                                 severity="warning", is_active=True)
        AlertEvent.objects.create(rule=r_ram, device=srv, metric="ram", value=88,
                                  threshold=85, severity="warning", status="firing",
                                  message="RAM al 88% en SRV-DATOS")
        AlertEvent.objects.create(rule=r_cpu, device=srv, metric="cpu", value=94,
                                  threshold=90, severity="critical", status="firing",
                                  message="CPU al 94% en SRV-DATOS")
        ev = AlertEvent.objects.create(rule=r_ram, device=pc, metric="ram", value=86,
                                       threshold=85, severity="warning", status="resolved",
                                       message="RAM normalizada en PC-BODEGA")
        AlertEvent.objects.filter(pk=ev.pk).update(resolved_at=timezone.now())

        # score: tendencia a la baja (el sistema detectó deterioro)
        self._score_history(c, [(30, 74, "C"), (14, 68, "D")])
        _safe_snapshot(c)


def _clamp(v, lo=1.0, hi=99.0):
    return max(lo, min(hi, v))


def _safe_snapshot(client):
    """Calcula y guarda el score actual real; si el motor no está, no rompe el seed."""
    try:
        from core.security_score import snapshot_security_score
        snapshot_security_score(client)
    except Exception:
        pass
