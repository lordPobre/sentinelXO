import logging
import hmac as hmac_lib, hashlib
from core.models import Client
from django.conf import settings
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import SessionAuthentication, BasicAuthentication 
from .serializers import TelemetryIngestSerializer
from core.alert_engine import evaluate_snapshot
from rest_framework.permissions import IsAuthenticated
from .models import HardwareDevice, TelemetrySnapshot
from core.throttles import TelemetryRateThrottle
from core.security import process_software_snapshot
from core.security import process_security_snapshot, notify_security_anomalies, update_network_stability, process_network_security


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """SessionAuthentication sin verificación CSRF — seguro para endpoints GET de solo lectura."""
    def enforce_csrf(self, request):
        pass  

logger = logging.getLogger("perseus")

def _process_printer_probes(client, probes):
    """
    Actualiza last_seen de las impresoras del cliente que respondieron al sondeo.
    'probes' = lista de {ip, online}. Una impresora online → last_seen=ahora,
    lo que la marca 'en línea' (igual que cualquier equipo, vía is_online).
    Las offline simplemente no se tocan: su last_seen envejece y caen a offline.
    """
    from django.utils import timezone
    online_ips = {
        p.get("ip") for p in probes
        if isinstance(p, dict) and p.get("online") and p.get("ip")
    }
    if not online_ips:
        return 0
    now = timezone.now()
    printers = HardwareDevice.objects.filter(
        client=client, device_type="printer", is_active=True,
        ip_address__in=online_ips,
    )
    updated = 0
    for pr in printers:
        pr.last_seen = now
        pr.save(update_fields=["last_seen"])
        updated += 1
    return updated

class TelemetryIngestView(APIView):
    """
    POST /api/v1/telemetry/
    Autenticación propia por agent_token — no usa sesión Django ni DRF Token.
    """
    authentication_classes = []
    permission_classes = []
    throttle_classes = ["core.throttles.TelemetryRateThrottle"]

    def get_throttles(self):
        
        return [TelemetryRateThrottle()]

    def post(self, request):
        # ── Validación HMAC (si el secreto está configurado) ─────────────────
        hmac_secret = getattr(settings, "SENTINEL_HMAC_SECRET", "").encode()
        if hmac_secret:
            sig_header = request.headers.get("X-Sentinel-Signature", "")
            if not sig_header.startswith("sha256="):
                logger.warning("Telemetría rechazada: falta header X-Sentinel-Signature")
                return Response({"error": "Firma requerida"}, status=status.HTTP_401_UNAUTHORIZED)
            
            expected = "sha256=" + hmac_lib.new(hmac_secret, request.body, hashlib.sha256).hexdigest()
            if not hmac_lib.compare_digest(expected, sig_header):
                logger.warning("Telemetría rechazada: firma HMAC inválida")
                return Response({"error": "Firma inválida"}, status=status.HTTP_401_UNAUTHORIZED)

        # ── Autenticación por token ──────────────────────────────────────────
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Token "):
            return Response({"error": "Token requerido"}, status=status.HTTP_401_UNAUTHORIZED)

        agent_token = auth_header.split(" ", 1)[1].strip()
        try:
            device = HardwareDevice.objects.select_related("client").get(
                agent_token=agent_token, is_active=True
            )
        except HardwareDevice.DoesNotExist:
            logger.warning(f"Telemetría con token inválido: {agent_token[:8]}...")
            return Response({"error": "Token inválido"}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = TelemetryIngestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data

        TelemetrySnapshot.objects.create(
            device=device,
            captured_at=data["timestamp"],
            cpu_percent=data["cpu_percent"],
            ram_used_percent=data["ram_used_percent"],
            ram_total_gb=data["ram_total_gb"],
            disk_usage=data.get("disk_partitions", []),
            uptime_seconds=data.get("uptime_seconds", 0),
            temperatures=data.get("temperatures", []),
            network=data.get("network", {}),
            cpu_freq_mhz=data.get("cpu_freq_mhz"),
            cpu_cores=data.get("cpu_cores"),
            cpu_threads=data.get("cpu_threads"),
            gpu_name=data.get("gpu_name", ""),
            gpu_usage_percent=data.get("gpu_usage_percent"),
            gpu_memory_used_percent=data.get("gpu_memory_used_percent"),
            gpu_memory_total_gb=data.get("gpu_memory_total_gb"),
            gpu_temp_celsius=data.get("gpu_temp_celsius"),
        )

        update_fields = ["last_seen"]
        device.last_seen = timezone.now()
        if data.get("os"):
            device.os = data["os"]
            update_fields.append("os")
        if data.get("os_version"):
            device.os_version = data["os_version"]
            update_fields.append("os_version")
        if data.get("ip_address"):
            device.ip_address = data["ip_address"]
            update_fields.append("ip_address")
        if data.get("hostname") and not device.hostname:
            device.hostname = data["hostname"]
            update_fields.append("hostname")
        device.save(update_fields=update_fields)

        try:
            net = data.get("network") or {}
            if any(k in net for k in ("latency_ms", "packet_loss_percent", "wifi")):
                update_network_stability(device, net)
        except Exception as e:
            logger.warning(f"Error actualizando estabilidad de red: {e}")

        logger.info(f"Telemetría recibida: {device.display_name} ({device.client})")

        try:  
            snap = TelemetrySnapshot.objects.filter(device=device).order_by("-captured_at").first()
            if snap:
                fired = evaluate_snapshot(snap)
                if fired:
                    logger.info(f"Alertas disparadas: {len(fired)} para {device.display_name}")
        except Exception as e:
            logger.error(f"Error en motor de alertas: {e}")

        try:
            security_snapshot = data.get("security_snapshot")
            if security_snapshot:
                logger.info(
                    f"Huella de seguridad recibida de {device.display_name}: "
                    f"{len(security_snapshot.get('local_admins', []))} admins, "
                    f"{len(security_snapshot.get('startup_programs', []))} programas de inicio, "
                    f"{len(security_snapshot.get('scheduled_tasks', []))} tareas"
                )
                anomalies = process_security_snapshot(device, security_snapshot)
                if anomalies:
                    notify_security_anomalies(device, anomalies)
                else:
                    logger.info(f"Huella de seguridad sin cambios para {device.display_name}")
        except Exception as e:
            logger.error(f"Error procesando huella de seguridad: {e}")

        try:
            net_sec = data.get("network_security")
            if net_sec:
                net_anomalies = process_network_security(device, net_sec)
                if net_anomalies:
                    notify_security_anomalies(device, net_anomalies)
                    logger.info(
                        f"Postura de red actualizada para {device.display_name}: "
                        f"{len(net_anomalies)} cambio(s)"
                    )
        except Exception as e:
            logger.error(f"Error procesando seguridad de red: {e}")

        try:
            software_inventory = data.get("software_inventory")
            if software_inventory:
                sw_anomalies = process_software_snapshot(device, software_inventory)
                if sw_anomalies:
                    logger.info(
                        f"Inventario de software actualizado para {device.display_name}: "
                        f"{len(software_inventory)} programas, {len(sw_anomalies)} cambio(s)"
                    )
        except Exception as e:
            logger.error(f"Error procesando inventario de software: {e}")
        
        try:
            printer_probes = request.data.get("printer_probes")
            if printer_probes:
                from core.printers import process_printer_status
                n = process_printer_status(device.client, printer_probes)
                if n:
                    logger.info(f"Impresoras: {n} en línea para {device.client}")
        except Exception as e:
            logger.warning(f"Error procesando impresoras: {e}")

        return Response({"status": "ok", "device": device.display_name}, status=status.HTTP_201_CREATED)


class DeviceStatusView(APIView):
    """GET /api/v1/devices/<token>/status/ — verificación de conectividad del agente"""
    authentication_classes = []
    permission_classes = []
    throttle_classes = []

    def get(self, request, token):
        try:
            device = HardwareDevice.objects.get(agent_token=token, is_active=True)
            return Response({"status": "ok", "device": device.display_name})
        except HardwareDevice.DoesNotExist:
            return Response({"error": "No encontrado"}, status=status.HTTP_404_NOT_FOUND)

class DeviceLiveView(APIView):
    """
    GET /api/v1/devices/<device_id>/live/
    Snapshot más reciente de un dispositivo. Usa sesión Django.
    """
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def get(self, request, device_id):
        try:
            device = HardwareDevice.objects.get(pk=device_id, is_active=True)
        except HardwareDevice.DoesNotExist:
            return Response({"error": "Dispositivo no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_staff:
            if not request.user.client_portals.filter(pk=device.client_id).exists():
                return Response({"error": "Sin acceso"}, status=status.HTTP_403_FORBIDDEN)

        snap = device.snapshots.first()
        if not snap:
            return Response({
                "device_id":    str(device_id),
                "display_name": device.display_name,
                "is_online":    device.is_online,
                "status":       device.status,
                "snapshot":     None,
                "last_seen":    device.last_seen.isoformat() if device.last_seen else None,
            })

        return Response({
            "device_id":    str(device_id),
            "display_name": device.display_name,
            "is_online":    device.is_online,
            "status":       device.status,
            "last_seen":    device.last_seen.isoformat() if device.last_seen else None,
            "snapshot": {
                "captured_at":      snap.captured_at.isoformat(),
                "cpu_percent":      snap.cpu_percent,
                "ram_used_percent": snap.ram_used_percent,
                "ram_total_gb":     snap.ram_total_gb,
                "disk_usage":       snap.disk_usage,
                "uptime_seconds":   snap.uptime_seconds,
                "uptime_human":     snap.uptime_human,
            },
        })


class ClientLiveSummaryView(APIView):
    """
    GET /api/v1/clients/<client_id>/live/
    Resumen en tiempo real de todos los dispositivos de un cliente.
    Usa SessionAuthentication para que el fetch() del dashboard funcione.
    """
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def get(self, request, client_id):
        try:
            if request.user.is_staff:
                client = Client.objects.get(pk=client_id)
            else:
                client = request.user.client_portals.get(pk=client_id, is_active=True)
        except Client.DoesNotExist:
            return Response({"error": "Cliente no encontrado"}, status=status.HTTP_404_NOT_FOUND)

        devices = client.devices.filter(is_active=True).prefetch_related("snapshots")
        devices_data = []
        for device in devices:
            snap = device.snapshots.first()
            devices_data.append({
                "id":           str(device.id),
                "name":         device.display_name,
                "is_online":    device.is_online,
                "status":       device.status,
                "last_seen":    device.last_seen.isoformat() if device.last_seen else None,
                "cpu":          snap.cpu_percent if snap else None,
                "ram":          snap.ram_used_percent if snap else None,
                "disk_usage":   snap.disk_usage if snap else [],
                "uptime_human": snap.uptime_human if snap else None,
            })

        online_count = sum(1 for d in devices_data if d["is_online"])
        return Response({
            "client_id":  str(client_id),
            "total":      len(devices_data),
            "online":     online_count,
            "offline":    len(devices_data) - online_count,
            "devices":    devices_data,
            "polled_at":  timezone.now().isoformat(),
        })


class DeviceHistoryView(APIView):
    """
    GET /api/v1/devices/<device_id>/history/?limit=120
    Últimos N snapshots de un dispositivo para los gráficos históricos.
    """
    authentication_classes = [CsrfExemptSessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = []

    def get(self, request, device_id):
        try:
            device = HardwareDevice.objects.get(pk=device_id, is_active=True)
        except HardwareDevice.DoesNotExist:
            return Response({"error": "No encontrado"}, status=status.HTTP_404_NOT_FOUND)

        if not request.user.is_staff:
            if not request.user.client_portals.filter(pk=device.client_id).exists():
                return Response({"error": "Sin acceso"}, status=status.HTTP_403_FORBIDDEN)

        limit = min(int(request.query_params.get("limit", 60)), 300)
        snapshots = list(
            device.snapshots.order_by("-captured_at")[:limit]
        )
        snapshots.reverse() 

        snap = snapshots[-1] if snapshots else None

        return Response({
            "device_id":    str(device_id),
            "display_name": device.display_name,
            "is_online":    device.is_online,
            "status":       device.status,
            "os":           device.os,
            "os_version":   device.os_version,
            "ip_address":   str(device.ip_address) if device.ip_address else None,
            "last_seen":    device.last_seen.isoformat() if device.last_seen else None,
            "current": {
                "cpu":          snap.cpu_percent if snap else None,
                "ram":          snap.ram_used_percent if snap else None,
                "ram_total_gb": snap.ram_total_gb if snap else None,
                "disk_usage":   snap.disk_usage if snap else [],
                "uptime_human": snap.uptime_human if snap else None,
                "temperatures": snap.temperatures if snap else [],
                "network":      snap.network if snap else {},
                "cpu_freq_mhz": snap.cpu_freq_mhz if snap else None,
                "cpu_cores":    snap.cpu_cores if snap else None,
                "cpu_threads":  snap.cpu_threads if snap else None,
            } if snap else None,
            "history": [
                {
                    "t":   timezone.localtime(s.captured_at).strftime("%H:%M:%S"),
                    "cpu": s.cpu_percent,
                    "ram": s.ram_used_percent,
                }
                for s in snapshots
            ],
        })
