#!/usr/bin/env python3
"""
Sentinel XO — Agente de Telemetría v4.0
Monitorea: CPU, RAM, disco, red, temperatura, GPU (NVIDIA/AMD/Intel)
"""
import os, sys, platform, socket, time, json, logging, random, hmac, hashlib
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("sentinel-agent")

# ── Cargar .env ────────────────────────────────────────────────────────────────
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
SECURITY_INTERVAL = int(os.environ.get("SENTINEL_SECURITY_INTERVAL", "300"))  # cada 5 min
HMAC_SECRET      = os.environ.get("SENTINEL_HMAC_SECRET", "").encode()        # firma HMAC-SHA256
IS_WINDOWS       = platform.system() == "Windows"


def get_local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return None


def get_temperatures():
    """
    Temperaturas del sistema.
    Windows: OpenHardwareMonitor (WMI) → fallback MSAcpi
    Linux/macOS: psutil.sensors_temperatures()
    Retorna lista de {label, current, high, critical}
    """
    temps = []

    if IS_WINDOWS:
        # Método principal: OpenHardwareMonitor expuesto por WMI
        try:
            import wmi
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

        # Fallback: zona ACPI si OHM no está corriendo
        if not temps:
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
                pass
    else:
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
            pass

    return temps


def get_gpu_stats():
    """
    Estadísticas de GPU. Soporta:
      - NVIDIA: pynvml  (pip install pynvml)
      - AMD/Intel/cualquier: OpenHardwareMonitor via WMI en Windows
      - Linux NVIDIA: también pynvml
    Retorna dict con gpu_name, gpu_usage_percent, gpu_memory_used_percent,
    gpu_memory_total_gb, gpu_temp_celsius  — o None si no hay GPU detectable.
    """

    # ── NVIDIA con pynvml (Windows y Linux) ──────────────────────────────────
    try:
        import pynvml
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

    # ── OpenHardwareMonitor en Windows (AMD, Intel, NVIDIA alternativo) ───────
    if IS_WINDOWS:
        try:
            import wmi
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
                # Detectar nombre de GPU desde hardware
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
                    # OHM reporta VRAM en MB
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

    # ── Linux: intentar GPUtil como alternativa ───────────────────────────────
    if not IS_WINDOWS:
        try:
            import GPUtil
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
    """Bytes enviados/recibidos desde el arranque."""
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


def get_local_admins():
    """Lista de cuentas en el grupo Administradores (solo Windows)."""
    if not IS_WINDOWS:
        return None
    try:
        import subprocess
        result = subprocess.run(
            ["net", "localgroup", "Administradores"],
            capture_output=True, text=True, timeout=10, encoding="cp850", errors="ignore"
        )
        text = result.stdout
        if "no existe" in text.lower() or "does not exist" in text.lower():
            result = subprocess.run(
                ["net", "localgroup", "Administrators"],
                capture_output=True, text=True, timeout=10, encoding="cp850", errors="ignore"
            )
            text = result.stdout

        # El listado de miembros está entre dos líneas de '----' y 'The command...'
        lines = text.splitlines()
        members = []
        in_members = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("---"):
                in_members = not in_members or len(members) == 0
                continue
            if stripped.startswith("The command completed") or not stripped:
                if in_members and members:
                    break
                continue
            if in_members or (not stripped.lower().startswith(("alias", "comentario",
                              "nombre", "comment", "name", "members"))
                              and "----" not in stripped):
                if stripped and stripped not in members:
                    members.append(stripped)

        # Filtrar líneas que no son nombres de usuario (headers residuales)
        members = [m for m in members if m and not m.lower().startswith(
            ("alias", "comentario", "comment", "nombre", "name", "miembros", "members"))]
        return sorted(set(members))
    except Exception as e:
        logger.warning(f"No se pudo leer administradores locales: {e}")
        return None


def get_startup_programs():
    """Programas configurados para ejecutarse al iniciar sesión/sistema (solo Windows)."""
    if not IS_WINDOWS:
        return None
    items = []
    seen = set()
    try:
        import winreg

        # (hive, path, source_label, access_flags_extra)
        # Para HKLM probamos la vista de 64 bits (KEY_WOW64_64KEY) y la de 32 bits
        # (KEY_WOW64_32KEY / WOW6432Node) para detectar entradas sin importar si el
        # agente corre como proceso de 32 o 64 bits.
        run_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                "HKLM\\Run (64bit)", winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                "HKLM\\Run (32bit)", winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
                "HKLM\\RunOnce (64bit)", winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
                "HKLM\\RunOnce (32bit)", winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                "HKCU\\Run", 0),
            (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\RunOnce",
                "HKCU\\RunOnce", 0),
        ]
        for hive, path, source_label, extra_flags in run_keys:
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | extra_flags) as key:
                    i = 0
                    while True:
                        try:
                            name, value, _ = winreg.EnumValue(key, i)
                            dedup_key = (source_label.split(" ")[0], name)  # ignora (64bit)/(32bit) para deduplicar
                            if dedup_key not in seen:
                                seen.add(dedup_key)
                                items.append({
                                    "name":   name,
                                    "command": str(value)[:300],
                                    "source": source_label,
                                })
                            i += 1
                        except OSError:
                            break
            except FileNotFoundError:
                continue
            except OSError:
                # KEY_WOW64_64KEY/32KEY puede no estar soportado en sistemas no-Windows-64
                continue
    except Exception as e:
        logger.warning(f"No se pudo leer programas de inicio: {e}")
        return None

    return items


def get_scheduled_tasks():
    """Tareas programadas activas, excluyendo las nativas de Microsoft (solo Windows)."""
    if not IS_WINDOWS:
        return None
    try:
        import subprocess
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=20, encoding="cp850", errors="ignore"
        )
        tasks = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith('"TaskName"'):
                continue
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 3:
                continue
            name = parts[0].strip('"').lstrip("\\")
            status = parts[2].strip('"') if len(parts) > 2 else ""
            # Excluir tareas nativas del sistema (Microsoft\...)
            if name.startswith("Microsoft\\") or not name:
                continue
            tasks.append({"name": name, "status": status})
        return tasks
    except Exception as e:
        logger.warning(f"No se pudo leer tareas programadas: {e}")
        return None


def collect_security_snapshot():
    """
    Recolecta una huella de seguridad del equipo: administradores locales,
    programas de inicio y tareas programadas. Solo Windows.
    Retorna None si no aplica (Linux/Mac) o si falló la recolección completa.
    """
    if not IS_WINDOWS:
        return None

    admins = get_local_admins()
    startup = get_startup_programs()
    tasks   = get_scheduled_tasks()

    if admins is None and startup is None and tasks is None:
        return None

    return {
        "local_admins":     admins if admins is not None else [],
        "startup_programs": startup if startup is not None else [],
        "scheduled_tasks":  tasks if tasks is not None else [],
    }


def collect(include_security=False):
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

    # Agregar huella de seguridad cada SECURITY_INTERVAL segundos (Windows)
    if include_security:
        try:
            sec = collect_security_snapshot()
            if sec is not None:
                payload["security_snapshot"] = sec
        except Exception as e:
            logger.warning(f"Error recolectando huella de seguridad: {e}")

    return payload


def send(payload):
    try:
        import urllib.request
        data = json.dumps(payload, sort_keys=True).encode()
        headers = {
            "Authorization": f"Token {SENTINEL_TOKEN}",
            "Content-Type":  "application/json",
            "User-Agent":    f"Sentinel XO-Agent/4.1 ({platform.system()})",
        }
        # Firma HMAC-SHA256 del payload para validación en el servidor
        if HMAC_SECRET:
            sig = hmac.new(HMAC_SECRET, data, hashlib.sha256).hexdigest()
            headers["X-Sentinel-Signature"] = f"sha256={sig}"
        req  = urllib.request.Request(
            SENTINEL_API_URL, data=data,
            headers=headers,
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

    last_security_send = 0.0

    while True:
        try:
            now = time.monotonic()
            send_security = IS_WINDOWS and (now - last_security_send >= SECURITY_INTERVAL)
            payload = collect(include_security=send_security)
            send(payload)
            if send_security:
                last_security_send = now
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
