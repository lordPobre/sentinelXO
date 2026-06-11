"""
Sentinel XO — Agente de Telemetría v4.0
Monitorea: CPU, RAM, disco, red, temperatura, GPU (NVIDIA/AMD/Intel)
"""
import wmi
import psutil
import pynvml
import GPUtil
import os, sys, platform, socket, time, json, logging, random
from datetime import datetime, timezone
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sentinel-agent")

_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())

SENTINEL_TOKEN   = os.environ.get("SENTINEL_TOKEN", "")
SENTINEL_API_URL = os.environ.get("SENTINEL_API_URL", "http://127.0.0.1:8000/api/v1/telemetry/")
INTERVAL         = int(os.environ.get("SENTINEL_INTERVAL", "5"))
TIMEOUT          = int(os.environ.get("SENTINEL_TIMEOUT", "10"))
IS_WINDOWS       = platform.system() == "Windows"


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return None


def get_temperatures():
    temps = []

    if IS_WINDOWS:
        try:
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            for s in w.Sensor():
                if s.SensorType == "Temperature":
                    temps.append({
                        "label":    s.Name,
                        "current":  round(float(s.Value), 1),
                        "high":     None,
                        "critical": None,
                    })
        except Exception:
            pass
        if not temps:
            try:
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
                pass
    else:
        try:
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
            pass

    return temps


def get_gpu_stats():
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)  # primera GPU
        name    = pynvml.nvmlDeviceGetName(handle)
        if isinstance(name, bytes):
            name = name.decode()
        util    = pynvml.nvmlDeviceGetUtilizationRates(handle)
        mem     = pynvml.nvmlDeviceGetMemoryInfo(handle)

        try:
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        except Exception:
            temp = None

        mem_total_gb = round(mem.total / 1024**3, 2)
        mem_pct      = round(mem.used / mem.total * 100, 1) if mem.total else None

        pynvml.nvmlShutdown()
        return {
            "gpu_name":                name,
            "gpu_usage_percent":       round(util.gpu, 1),
            "gpu_memory_used_percent": mem_pct,
            "gpu_memory_total_gb":     mem_total_gb,
            "gpu_temp_celsius":        float(temp) if temp is not None else None,
        }
    except Exception:
        pass

    if IS_WINDOWS:
        try:
            w = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            sensors = w.Sensor()

            gpu_name    = None
            gpu_usage   = None
            gpu_mem_pct = None
            gpu_mem_gb  = None
            gpu_temp    = None
            gpu_mem_used_gb  = None

            for s in sensors:
                hw = s.Parent if hasattr(s, "Parent") else ""
                try:
                    for hw_item in w.Hardware():
                        if hw_item.HardwareType in ("GpuNvidia", "GpuAti"):
                            gpu_name = hw_item.Name
                            break
                except Exception:
                    pass

                name_lower = s.Name.lower()
                stype      = s.SensorType

                if stype == "Load" and "gpu core" in name_lower:
                    gpu_usage = round(float(s.Value), 1)
                elif stype == "Temperature" and "gpu core" in name_lower:
                    gpu_temp = round(float(s.Value), 1)
                elif stype == "SmallData" and "gpu memory used" in name_lower:
                    gpu_mem_used_gb = round(float(s.Value) / 1024, 2)
                elif stype == "SmallData" and "gpu memory total" in name_lower:
                    gpu_mem_gb = round(float(s.Value) / 1024, 2)

            if gpu_usage is not None or gpu_temp is not None:
                mem_pct = None
                if gpu_mem_used_gb and gpu_mem_gb and gpu_mem_gb > 0:
                    mem_pct = round(gpu_mem_used_gb / gpu_mem_gb * 100, 1)
                return {
                    "gpu_name":                gpu_name or "GPU",
                    "gpu_usage_percent":       gpu_usage,
                    "gpu_memory_used_percent": mem_pct,
                    "gpu_memory_total_gb":     gpu_mem_gb,
                    "gpu_temp_celsius":        gpu_temp,
                }
        except Exception:
            pass

    if not IS_WINDOWS:
        try:
            gpus = GPUtil.getGPUs()
            if gpus:
                g = gpus[0]
                return {
                    "gpu_name":                g.name,
                    "gpu_usage_percent":       round(g.load * 100, 1),
                    "gpu_memory_used_percent": round(g.memoryUtil * 100, 1),
                    "gpu_memory_total_gb":     round(g.memoryTotal / 1024, 2),
                    "gpu_temp_celsius":        float(g.temperature),
                }
        except Exception:
            pass

    return None  # sin GPU detectable


def get_network_stats():
    try:
        import psutil
        net = psutil.net_io_counters()
        return {
            "bytes_sent":   net.bytes_sent,
            "bytes_recv":   net.bytes_recv,
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

    cpu      = psutil.cpu_percent(interval=1)
    cpu_freq = psutil.cpu_freq()
    ram      = psutil.virtual_memory()
    disks    = []

    for p in psutil.disk_partitions(all=False):
        if not p.fstype or p.fstype in ("cdfs", "udf"):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
            disks.append({
                "mountpoint":   p.mountpoint,
                "total_gb":     round(u.total / 1024**3, 2),
                "used_percent": round(u.percent, 1),
            })
        except (PermissionError, OSError):
            continue

    temperatures = get_temperatures()
    network      = get_network_stats()
    gpu          = get_gpu_stats()

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

    # Agregar GPU solo si se detectó
    if gpu:
        payload.update(gpu)

    return payload


def send(payload):
    try:
        import urllib.request
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(
            SENTINEL_API_URL, data=data,
            headers={
                "Authorization": f"Token {SENTINEL_TOKEN}",
                "Content-Type":  "application/json",
                "User-Agent":    f"Sentinel XO-Agent/4.0 ({platform.system()})",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = json.loads(r.read().decode())

            # Log detallado
            parts = [
                f"OK → {body.get('device','?')}",
                f"cpu={payload['cpu_percent']}%",
                f"ram={payload['ram_used_percent']}%",
            ]
            if payload.get("temperatures"):
                t = payload["temperatures"][0]
                parts.append(f"temp={t['current']}°C")
            if payload.get("gpu_name"):
                parts.append(f"gpu={payload.get('gpu_usage_percent','?')}%")
                if payload.get("gpu_temp_celsius"):
                    parts.append(f"gpu_temp={payload['gpu_temp_celsius']}°C")
            logger.info("  ".join(parts))
            return True
    except Exception as e:
        logger.warning(f"Error al enviar: {e}")
        return False


def main():
    if not SENTINEL_TOKEN:
        logger.error("SENTINEL_TOKEN no configurado en .env")
        sys.exit(1)

    logger.info(f"Sentinel XO Agent v4.0 | host={platform.node()} | intervalo={INTERVAL}s")
    logger.info(f"Enviando a: {SENTINEL_API_URL}")

    # Diagnóstico inicial
    temps = get_temperatures()
    if temps:
        logger.info(f"Temperatura: {len(temps)} sensor(es) disponibles")
    else:
        logger.info("Temperatura: no disponible")
        if IS_WINDOWS:
            logger.info("  → Instalar OpenHardwareMonitor + pip install wmi")

    gpu = get_gpu_stats()
    if gpu:
        logger.info(f"GPU detectada: {gpu['gpu_name']}")
        if gpu.get("gpu_memory_total_gb"):
            logger.info(f"  VRAM: {gpu['gpu_memory_total_gb']} GB")
    else:
        logger.info("GPU: no detectada o sin librerías")
        logger.info("  → NVIDIA: pip install pynvml")
        logger.info("  → AMD/Intel (Windows): instalar OpenHardwareMonitor")

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
