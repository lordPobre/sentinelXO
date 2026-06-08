#!/usr/bin/env python3
"""
Perseus Technology — Agente de Telemetría v3.0
Monitorea: CPU, RAM, disco, red, temperatura
"""
import os, sys, platform, socket, time, json, logging, random
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("perseus-agent")

# ─── Cargar .env ──────────────────────────────────────────────────────────────
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

PERSEUS_TOKEN   = os.environ.get("PERSEUS_TOKEN", "")
PERSEUS_API_URL = os.environ.get("PERSEUS_API_URL", "http://127.0.0.1:8000/api/v1/telemetry/")
INTERVAL        = int(os.environ.get("PERSEUS_INTERVAL", "5"))
TIMEOUT         = int(os.environ.get("PERSEUS_TIMEOUT", "10"))
IS_WINDOWS      = platform.system() == "Windows"


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return None


def get_temperatures():
    """
    Obtiene temperaturas del sistema.
    - Windows: usa wmi (pip install wmi)
    - Linux/macOS: usa psutil.sensors_temperatures()
    Retorna lista de {label, current, high, critical}
    """
    temps = []

    if IS_WINDOWS:
        try:
            import wmi
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            sensors = w.Sensor()
            for s in sensors:
                if s.SensorType == "Temperature":
                    temps.append({
                        "label":    s.Name,
                        "current":  round(float(s.Value), 1),
                        "high":     None,
                        "critical": None,
                    })
        except Exception:
            # Fallback: WMI estándar (menos detallado pero siempre disponible)
            try:
                import wmi
                w = wmi.WMI()
                for item in w.MSAcpi_ThermalZoneTemperature():
                    celsius = (item.CurrentTemperature / 10.0) - 273.15
                    temps.append({
                        "label":    "Thermal Zone",
                        "current":  round(celsius, 1),
                        "high":     None,
                        "critical": None,
                    })
            except Exception:
                pass  # wmi no instalado o no disponible
    else:
        # Linux / macOS
        try:
            import psutil
            sensors = psutil.sensors_temperatures()
            for name, entries in sensors.items():
                for entry in entries:
                    temps.append({
                        "label":    f"{name}/{entry.label}" if entry.label else name,
                        "current":  round(entry.current, 1),
                        "high":     entry.high,
                        "critical": entry.critical,
                    })
        except (AttributeError, Exception):
            pass  # no disponible en esta plataforma

    return temps


def get_network_stats():
    """Bytes enviados/recibidos desde el arranque."""
    try:
        import psutil
        net = psutil.net_io_counters()
        return {
            "bytes_sent": net.bytes_sent,
            "bytes_recv": net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }
    except Exception:
        return {}


def collect():
    try:
        import psutil
    except ImportError:
        logger.error("Falta psutil: pip install psutil")
        sys.exit(1)

    cpu     = psutil.cpu_percent(interval=1)
    cpu_freq = psutil.cpu_freq()
    ram     = psutil.virtual_memory()
    disks   = []

    for p in psutil.disk_partitions(all=False):
        if not p.fstype or p.fstype in ("cdfs", "udf"):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append({
                "mountpoint": p.mountpoint,
                "total_gb":   round(u.total / 1024**3, 2),
                "used_percent": round(u.percent, 1),
            })
        except (PermissionError, OSError):
            continue

    temperatures = get_temperatures()
    network      = get_network_stats()

    payload = {
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "hostname":         platform.node(),
        "os":               platform.system(),
        "os_version":       platform.version()[:200],
        "cpu_percent":      round(cpu, 1),
        "cpu_freq_mhz":     round(cpu_freq.current, 0) if cpu_freq else None,
        "cpu_cores":        psutil.cpu_count(logical=False),
        "cpu_threads":      psutil.cpu_count(logical=True),
        "ram_total_gb":     round(ram.total / 1024**3, 2),
        "ram_used_percent": round(ram.percent, 1),
        "disk_partitions":  disks,
        "temperatures":     temperatures,
        "network":          network,
        "uptime_seconds":   int(datetime.now(timezone.utc).timestamp() - psutil.boot_time()),
        "ip_address":       get_local_ip(),
    }

    return payload


def send(payload):
    try:
        import urllib.request
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            PERSEUS_API_URL, data=data,
            headers={
                "Authorization": f"Token {PERSEUS_TOKEN}",
                "Content-Type":  "application/json",
                "User-Agent":    f"Perseus-Agent/3.0 ({platform.system()})",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode())
            temp_str = ""
            if payload.get("temperatures"):
                t = payload["temperatures"][0]
                temp_str = f"  temp={t['current']}°C"
            logger.info(
                f"OK → {body.get('device','?')}"
                f"  cpu={payload['cpu_percent']}%"
                f"  ram={payload['ram_used_percent']}%"
                f"{temp_str}"
            )
            return True
    except Exception as e:
        logger.warning(f"Error al enviar: {e}")
        return False


def main():
    if not PERSEUS_TOKEN:
        logger.error("PERSEUS_TOKEN no configurado en .env")
        sys.exit(1)

    logger.info(f"Perseus Agent v3.0 | host={platform.node()} | intervalo={INTERVAL}s")
    logger.info(f"Enviando a: {PERSEUS_API_URL}")

    # Verificar temperatura disponible
    temps = get_temperatures()
    if temps:
        logger.info(f"Temperatura disponible: {len(temps)} sensor(es)")
    else:
        logger.info("Temperatura: no disponible en este sistema")
        if IS_WINDOWS:
            logger.info("  → Para activarla: pip install wmi + instalar OpenHardwareMonitor")

    time.sleep(random.uniform(0, min(INTERVAL, 3)))

    while True:
        try:
            payload = collect()
            send(payload)
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
