"""
Tests de la app core de Sentinel XO.

Cubren las piezas de mayor riesgo:
  - Endpoint de ingestión de telemetría (autenticación por token, validación,
    creación de snapshots). Aquí vivía el bug del import de `settings`.
  - Motor de alertas (umbrales, cooldown, métricas no disponibles).
  - Tarea de purga de telemetría antigua.

Se ejecutan con: python manage.py test core
"""
import json
from datetime import timedelta
from core.tasks import purge_old_telemetry
from core.models import NetworkSnapshot
from core.security import process_network_security, update_network_stability
from core.alert_engine import evaluate_snapshot
from core.serializers import TelemetryIngestSerializer
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import (
    Client, HardwareDevice, TelemetrySnapshot, AlertRule, AlertEvent,
)


def _client(**kw):
    """Crea un Client con valores por defecto válidos (rut único)."""
    n = Client.objects.count() + 1
    defaults = dict(
        company_name=f"Cliente {n}",
        rut=f"{10000000 + n}-{n % 10}",
        contact_email=f"cliente{n}@example.com",
    )
    defaults.update(kw)
    return Client.objects.create(**defaults)


def _device(client, **kw):
    defaults = dict(hostname="PC-TEST", device_type="workstation")
    defaults.update(kw)
    return HardwareDevice.objects.create(client=client, **defaults)


def _payload(**overrides):
    """Payload mínimo válido para el endpoint de ingestión."""
    p = {
        "timestamp": timezone.now().isoformat(),
        "hostname": "PC-TEST",
        "cpu_percent": 25.0,
        "ram_total_gb": 16.0,
        "ram_used_percent": 40.0,
    }
    p.update(overrides)
    return p


@override_settings(SECURE_SSL_REDIRECT=False, SENTINEL_DISABLE_AI_DIAGNOSIS=True)
class TelemetryIngestTests(TestCase):
    """Endpoint POST /api/v1/telemetry/."""
    def setUp(self):
        self.client_obj = _client()
        self.device = _device(self.client_obj)
        self.url = reverse("api:telemetry-ingest")

    def _post(self, payload, token=None):
        headers = {}
        if token is not None:
            headers["HTTP_AUTHORIZATION"] = f"Token {token}"
        return self.client.post(
            self.url, data=json.dumps(payload),
            content_type="application/json", **headers,
        )

    def test_token_valido_crea_snapshot(self):
        resp = self._post(_payload(), token=self.device.agent_token)
        self.assertIn(resp.status_code, (200, 201))
        self.assertEqual(TelemetrySnapshot.objects.filter(device=self.device).count(), 1)
        snap = TelemetrySnapshot.objects.get(device=self.device)
        self.assertEqual(snap.cpu_percent, 25.0)
        self.assertEqual(snap.ram_used_percent, 40.0)

    def test_actualiza_last_seen(self):
        self.assertIsNone(self.device.last_seen)
        self._post(_payload(), token=self.device.agent_token)
        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_seen)

    def test_sin_token_rechazado(self):
        resp = self._post(_payload(), token=None)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(TelemetrySnapshot.objects.count(), 0)

    def test_token_invalido_rechazado(self):
        resp = self._post(_payload(), token="token-que-no-existe")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(TelemetrySnapshot.objects.count(), 0)

    def test_dispositivo_inactivo_rechazado(self):
        self.device.is_active = False
        self.device.save(update_fields=["is_active"])
        resp = self._post(_payload(), token=self.device.agent_token)
        self.assertEqual(resp.status_code, 401)

    def test_payload_invalido_devuelve_400(self):
        resp = self._post(_payload(cpu_percent=250.0), token=self.device.agent_token)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(TelemetrySnapshot.objects.count(), 0)

    def test_ingestion_no_purga_en_caliente(self):
        old = TelemetrySnapshot.objects.create(
            device=self.device,
            captured_at=timezone.now() - timedelta(days=60),
            cpu_percent=5.0, ram_used_percent=5.0, ram_total_gb=16.0,
        )
        self._post(_payload(), token=self.device.agent_token)
        self.assertTrue(TelemetrySnapshot.objects.filter(pk=old.pk).exists())
    
    def _net_sec(self, **kw):
        """Dict de seguridad de red como el que envía el agente v4.2."""
        base = dict(
            wifi_encryption="WPA2-Personal",
            wifi_ssid="OficinaWiFi",
            network_category="Private",
            firewall=[{"name": "Domain", "enabled": True},
                      {"name": "Private", "enabled": True},
                      {"name": "Public", "enabled": True}],
            dns_servers=["8.8.8.8"],
        )
        base.update(kw)
        return base

    def test_serializer_conserva_network_security(self):
        """Regresión Bug 5: el serializer NO debe descartar network_security.
        Con el campo sin declarar, DRF lo quitaba de validated_data."""
        serializer = TelemetryIngestSerializer(data=_payload(network_security=self._net_sec()))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertIn("network_security", serializer.validated_data)
        self.assertEqual(
            serializer.validated_data["network_security"]["wifi_encryption"],
            "WPA2-Personal",
        )

    def test_ingesta_con_network_security_crea_postura_de_red(self):
        """Regresión Bug 5 extremo a extremo: un POST con network_security debe
        crear la NetworkSnapshot del dispositivo con esos campos. Antes del fix,
        el serializer descartaba el campo y la postura de red nunca se procesaba."""
        resp = self._post(_payload(network_security=self._net_sec()),
                          token=self.device.agent_token)
        self.assertIn(resp.status_code, (200, 201))
        self.assertTrue(NetworkSnapshot.objects.filter(device=self.device).exists())
        snap = NetworkSnapshot.objects.get(device=self.device)
        self.assertEqual(snap.wifi_encryption, "WPA2-Personal")
        self.assertEqual(snap.wifi_ssid, "OficinaWiFi")
        self.assertEqual(snap.network_category, "Private")
        self.assertEqual(snap.dns_servers, ["8.8.8.8"])
        self.assertIs(snap.firewall_all_on, True)
        self.assertFalse(snap.is_open_wifi)

    def test_ingesta_sin_network_security_no_crea_postura(self):
        """Control: sin network_security, no se crea NetworkSnapshot — así el test
        anterior prueba el procesamiento real y no un efecto colateral."""
        self._post(_payload(), token=self.device.agent_token)
        self.assertFalse(NetworkSnapshot.objects.filter(device=self.device).exists())


@override_settings(SENTINEL_DISABLE_AI_DIAGNOSIS=True)
class AlertEngineTests(TestCase):
    """Motor de alertas: evaluate_snapshot."""
    def setUp(self):
        self.evaluate = evaluate_snapshot
        self.client_obj = _client()
        self.device = _device(self.client_obj)

    def _snapshot(self, **kw):
        defaults = dict(
            device=self.device, captured_at=timezone.now(),
            cpu_percent=10.0, ram_used_percent=10.0, ram_total_gb=16.0,
        )
        defaults.update(kw)
        return TelemetrySnapshot.objects.create(**defaults)

    def test_supera_umbral_dispara_alerta(self):
        AlertRule.objects.create(
            client=self.client_obj, metric="cpu", threshold=90.0,
            severity="critical", cooldown_minutes=30,
        )
        snap = self._snapshot(cpu_percent=95.0)
        fired = self.evaluate(snap)
        self.assertEqual(len(fired), 1)
        self.assertEqual(AlertEvent.objects.count(), 1)

    def test_bajo_umbral_no_dispara(self):
        AlertRule.objects.create(
            client=self.client_obj, metric="cpu", threshold=90.0,
            severity="critical", cooldown_minutes=30,
        )
        snap = self._snapshot(cpu_percent=50.0)
        fired = self.evaluate(snap)
        self.assertEqual(len(fired), 0)
        self.assertEqual(AlertEvent.objects.count(), 0)

    def test_cooldown_evita_alerta_duplicada(self):
        rule = AlertRule.objects.create(
            client=self.client_obj, metric="cpu", threshold=90.0,
            severity="critical", cooldown_minutes=30,
        )
        self.evaluate(self._snapshot(cpu_percent=95.0))
        fired = self.evaluate(self._snapshot(cpu_percent=96.0))
        self.assertEqual(len(fired), 0)
        self.assertEqual(AlertEvent.objects.filter(rule=rule).count(), 1)

    def test_regla_inactiva_no_dispara(self):
        AlertRule.objects.create(
            client=self.client_obj, metric="cpu", threshold=90.0,
            severity="critical", is_active=False, cooldown_minutes=30,
        )
        fired = self.evaluate(self._snapshot(cpu_percent=99.0))
        self.assertEqual(len(fired), 0)

    def test_metrica_no_disponible_se_ignora(self):
        AlertRule.objects.create(
            client=self.client_obj, metric="gpu_usage", threshold=90.0,
            severity="warning", cooldown_minutes=30,
        )
        fired = self.evaluate(self._snapshot(gpu_usage_percent=None))
        self.assertEqual(len(fired), 0)

    def test_regla_de_otro_cliente_no_aplica(self):
        otro = _client()
        AlertRule.objects.create(
            client=otro, metric="cpu", threshold=10.0,
            severity="warning", cooldown_minutes=30,
        )
        fired = self.evaluate(self._snapshot(cpu_percent=99.0))
        self.assertEqual(len(fired), 0)


class PurgeTelemetryTaskTests(TestCase):
    """Tarea core.purge_old_telemetry."""

    def setUp(self):
        self.client_obj = _client()
        self.device = _device(self.client_obj)

    def _snap_age(self, days):
        return TelemetrySnapshot.objects.create(
            device=self.device,
            captured_at=timezone.now() - timedelta(days=days),
            cpu_percent=1.0, ram_used_percent=1.0, ram_total_gb=8.0,
        )

    def test_borra_antiguos_conserva_recientes(self):
        
        for d in (40, 35, 31):
            self._snap_age(d)
        for d in (20, 5, 1):
            self._snap_age(d)
        result = purge_old_telemetry()
        self.assertEqual(result["deleted"], 3)
        self.assertEqual(TelemetrySnapshot.objects.count(), 3)

    @override_settings(SENTINEL_TELEMETRY_RETENTION_DAYS=3)
    def test_retencion_configurable(self):
        from core.tasks import purge_old_telemetry
        self._snap_age(5)
        self._snap_age(1)
        result = purge_old_telemetry()
        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["retention_days"], 3)
        self.assertEqual(TelemetrySnapshot.objects.count(), 1)

    def test_sin_datos_no_falla(self):
        
        result = purge_old_telemetry()
        self.assertEqual(result["deleted"], 0)


@override_settings(SENTINEL_DISABLE_AI_DIAGNOSIS=True)
class NetworkSnapshotTests(TestCase):
    """Procesamiento y evaluación de la postura de red."""

    def setUp(self):
        self.client_obj = _client()
        self.device = _device(self.client_obj)

    def _net_sec(self, **kw):
        base = dict(
            wifi_encryption="WPA2-Personal",
            wifi_ssid="OficinaWiFi",
            network_category="Private",
            firewall=[{"name": "Domain", "enabled": True},
                      {"name": "Private", "enabled": True},
                      {"name": "Public", "enabled": True}],
            dns_servers=["8.8.8.8"],
        )
        base.update(kw)
        return base

    def test_primera_vez_sin_alertas(self):
        from core.security import process_network_security
        anomalies = process_network_security(self.device, self._net_sec())
        self.assertEqual(len(anomalies), 0)  
        self.assertTrue(hasattr(self.device, "network_snapshot"))

    def test_wifi_abierta_es_critico(self):
        from core.security import process_network_security
        from core.models import NetworkSnapshot
        process_network_security(self.device, self._net_sec())  
        anomalies = process_network_security(
            self.device, self._net_sec(wifi_encryption="", wifi_ssid="CafeWiFi"))
        snap = NetworkSnapshot.objects.get(device=self.device)
        self.assertEqual(snap.risk_level, "critical")
        self.assertTrue(any(a.anomaly_type == "open_wifi" for a in anomalies))

    def test_firewall_apagado_genera_alerta_critica(self):
        from core.security import process_network_security
        process_network_security(self.device, self._net_sec())  
        anomalies = process_network_security(
            self.device,
            self._net_sec(firewall=[{"name": "Public", "enabled": False},
                                    {"name": "Private", "enabled": True},
                                    {"name": "Domain", "enabled": True}]))
        self.assertTrue(any(a.anomaly_type == "firewall_off" and a.severity == "critical"
                            for a in anomalies))

    def test_cambio_de_red_wifi(self):
        process_network_security(self.device, self._net_sec(wifi_ssid="RedA"))
        anomalies = process_network_security(self.device, self._net_sec(wifi_ssid="RedB"))
        self.assertTrue(any(a.anomaly_type == "network_change" for a in anomalies))

    def test_cambio_de_dns_genera_alerta(self):
        process_network_security(self.device, self._net_sec(dns_servers=["8.8.8.8"]))
        anomalies = process_network_security(
            self.device, self._net_sec(dns_servers=["1.2.3.4"]))
        self.assertTrue(any(a.anomaly_type == "dns_change" for a in anomalies))

    def test_red_segura_sin_alertas(self):
        process_network_security(self.device, self._net_sec())
        anomalies = process_network_security(self.device, self._net_sec())  # sin cambios
        snap = NetworkSnapshot.objects.get(device=self.device)
        self.assertEqual(snap.risk_level, "ok")
        self.assertEqual(len(anomalies), 0)

    def test_estabilidad_actualiza_sin_alertas(self):
        update_network_stability(self.device, {
            "latency_ms": 25.0, "packet_loss_percent": 0.0,
            "wifi": {"ssid": "OficinaWiFi", "signal_percent": 85},
        })
        snap = NetworkSnapshot.objects.get(device=self.device)
        self.assertEqual(snap.latency_ms, 25.0)
        self.assertEqual(snap.wifi_signal_percent, 85)

    def test_perdida_paquetes_alta_es_warning(self):
        process_network_security(self.device, self._net_sec())
        update_network_stability(self.device, {"latency_ms": 30.0, "packet_loss_percent": 25.0})
        process_network_security(self.device, self._net_sec())
        snap = NetworkSnapshot.objects.get(device=self.device)
        self.assertIn(snap.risk_level, ("warning", "critical"))
