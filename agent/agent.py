#!/usr/bin/env python3
"""
Sentinel XO — Agente de Telemetría v4.2
Monitorea: CPU, RAM, disco, red, temperatura, GPU (NVIDIA/AMD/Intel),
huella de seguridad (administradores locales, inicio, tareas programadas)
e inventario de software instalado
"""
import os, sys, platform, socket, time, json, logging, random, hmac, hashlib
import urllib.request, wmi, psutil, pynvml, GPUtil, winreg
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
SECURITY_INTERVAL = int(os.environ.get("SENTINEL_SECURITY_INTERVAL", "300"))  
SOFTWARE_INTERVAL = int(os.environ.get("SENTINEL_SOFTWARE_INTERVAL", "21600"))  
NET_QUALITY_INTERVAL = int(os.environ.get("SENTINEL_NETQUALITY_INTERVAL", "60"))  
HMAC_SECRET      = os.environ.get("SENTINEL_HMAC_SECRET", "").encode()        
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

    # ── Linux: intentar GPUtil como alternativa ───────────────────────────────
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

    return None 


def _ping_gateway():
    """
    Mide latencia (ms) y pérdida de paquetes (%) haciendo ping al gateway por
    defecto. Devuelve (latency_ms, packet_loss_pct) o (None, None) si falla.
    """
    try:
        import subprocess, re
        if IS_WINDOWS:
            out = subprocess.run(["ipconfig"], capture_output=True, text=True,
                                 timeout=8, encoding="cp850", errors="ignore").stdout
            m = re.search(r"(?:Default Gateway|Puerta de enlace predeterminada)[ .]*:\s*([\d.]+)", out)
            gateway = m.group(1) if m else None
        else:
            out = subprocess.run(["ip", "route"], capture_output=True, text=True,
                                 timeout=8, errors="ignore").stdout
            m = re.search(r"default via ([\d.]+)", out)
            gateway = m.group(1) if m else None

        if not gateway:
            return None, None

        if IS_WINDOWS:
            r = subprocess.run(["ping", "-n", "4", "-w", "1000", gateway],
                               capture_output=True, text=True, timeout=12,
                               encoding="cp850", errors="ignore").stdout
            lat = re.search(r"(?:Average|Media)[ =]*([\d]+)ms", r)
            loss = re.search(r"\((\d+)%\s*(?:loss|perdidos)\)", r)
        else:
            r = subprocess.run(["ping", "-c", "4", "-W", "1", gateway],
                               capture_output=True, text=True, timeout=12,
                               errors="ignore").stdout
            lat = re.search(r"= [\d.]+/([\d.]+)/", r)
            loss = re.search(r"(\d+)% packet loss", r)

        latency = float(lat.group(1)) if lat else None
        packet_loss = float(loss.group(1)) if loss else None
        return latency, packet_loss
    except Exception:
        return None, None


def _wifi_info():
    """
    Devuelve dict con info de la conexión WiFi (solo Windows): SSID, señal %,
    tipo de cifrado. Si no hay WiFi (cable) o falla, devuelve {}.
    """
    if not IS_WINDOWS:
        return {}
    try:
        import subprocess, re
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"],
                             capture_output=True, text=True, timeout=10,
                             encoding="cp850", errors="ignore").stdout
        if not out or ("There is no wireless" in out or "no hay interfaz" in out.lower()):
            return {}

        def grab(*patterns):
            for p in patterns:
                m = re.search(p + r"\s*:\s*(.+)", out)
                if m:
                    return m.group(1).strip()
            return None

        ssid = grab(r"\bSSID", r"\bSSID")
        signal = grab(r"(?:Signal|Señal)")
        auth = grab(r"(?:Authentication|Autenticación)")
        signal_pct = None
        if signal:
            sm = re.search(r"(\d+)", signal)
            signal_pct = int(sm.group(1)) if sm else None

        return {
            "ssid": ssid,
            "signal_percent": signal_pct,
            "encryption": auth,  
        }
    except Exception:
        return {}


def get_network_stats():
    """
    Métricas de red: bytes/paquetes (contadores), más latencia, pérdida de
    paquetes y calidad WiFi. Estos últimos solo se muestrean cuando se solicita
    (sample_quality=True) para no hacer ping en cada ciclo.
    """
    stats = {}
    try:
        net = psutil.net_io_counters()
        stats = {
            "bytes_sent":   net.bytes_sent,
            "bytes_recv":   net.bytes_recv,
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        }
    except Exception:
        return {}

    return stats


def get_network_quality():
    """
    Muestreo de calidad de red (latencia, pérdida, WiFi). Más costoso que
    get_network_stats, se llama con menor frecuencia.
    """
    latency, packet_loss = _ping_gateway()
    quality = {
        "latency_ms": latency,
        "packet_loss_percent": packet_loss,
    }
    wifi = _wifi_info()
    if wifi:
        quality["wifi"] = wifi
    return quality


def get_network_security():
    """
    Postura de seguridad de la red a la que está conectado el equipo (Windows):
    - Perfil de red (Public/Private/DomainAuthenticated)
    - Estado del firewall por perfil
    - Servidores DNS configurados
    - Tipo de cifrado WiFi (si aplica)
    Devuelve dict, o None si no es Windows.
    """
    if not IS_WINDOWS:
        return None
    try:
        import subprocess, re, json as _json
        result = {}

        ps_cmd = (
            "$p = Get-NetConnectionProfile | Select-Object -First 1; "
            "$fw = Get-NetFirewallProfile | Select-Object Name,Enabled; "
            "$o = @{ network_category = $p.NetworkCategory; "
            "interface_alias = $p.InterfaceAlias; "
            "firewall = ($fw | ForEach-Object { @{ name=$_.Name; enabled=[bool]$_.Enabled } }) }; "
            "$o | ConvertTo-Json -Compress -Depth 4"
        )
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd],
                             capture_output=True, text=True, timeout=15,
                             encoding="utf-8", errors="ignore").stdout.strip()
        if out:
            try:
                data = _json.loads(out)
                result["network_category"] = data.get("network_category")
                result["interface_alias"] = data.get("interface_alias")
                fw = data.get("firewall")
                if isinstance(fw, dict):
                    fw = [fw]
                result["firewall"] = fw or []
            except Exception:
                pass

        dns_out = subprocess.run(["ipconfig", "/all"], capture_output=True, text=True,
                                 timeout=10, encoding="cp850", errors="ignore").stdout
        dns_servers = re.findall(r"(?:DNS Servers|Servidores DNS)[ .]*:\s*([\d.]+)", dns_out)
        result["dns_servers"] = dns_servers

        wifi = _wifi_info()
        if wifi:
            result["wifi_encryption"] = wifi.get("encryption")
            result["wifi_ssid"] = wifi.get("ssid")

        return result
    except Exception as e:
        return {"error": str(e)[:200]}


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
                            dedup_key = (source_label.split(" ")[0], name)  
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
            if name.startswith("Microsoft\\") or not name:
                continue
            tasks.append({"name": name, "status": status})
        return tasks
    except Exception as e:
        logger.warning(f"No se pudo leer tareas programadas: {e}")
        return None


def get_installed_software():
    """
    Lista de software instalado, leído desde las claves de registro Uninstall
    (HKLM 64bit, HKLM 32bit/WOW6432Node, HKCU). Solo Windows.
    Retorna lista de {name, version, publisher}, deduplicada.
    """
    if not IS_WINDOWS:
        return None
    items = []
    seen = set()
    try:

        uninstall_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                winreg.KEY_WOW64_64KEY),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                winreg.KEY_WOW64_32KEY),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
        ]
        for hive, path, extra_flags in uninstall_keys:
            try:
                with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | extra_flags) as key:
                    i = 0
                    while True:
                        try:
                            subkey_name = winreg.EnumKey(key, i)
                            i += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(key, subkey_name) as sub:
                                def _get(name):
                                    try:
                                        return winreg.QueryValueEx(sub, name)[0]
                                    except FileNotFoundError:
                                        return None

                                display_name = _get("DisplayName")
                                if not display_name:
                                    continue
                                if _get("SystemComponent") == 1:
                                    continue
                                if _get("ParentKeyName"):
                                    continue

                                version   = _get("DisplayVersion") or ""
                                publisher = _get("Publisher") or ""

                                dedup_key = (display_name.strip().lower(), str(version).strip())
                                if dedup_key in seen:
                                    continue
                                seen.add(dedup_key)
                                items.append({
                                    "name":      display_name.strip(),
                                    "version":   str(version).strip(),
                                    "publisher": publisher.strip(),
                                })
                        except OSError:
                            continue
            except FileNotFoundError:
                continue
            except OSError:
                continue
    except Exception as e:
        logger.warning(f"No se pudo leer software instalado: {e}")
        return None

    items.sort(key=lambda x: x["name"].lower())
    return items


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


def collect(include_security=False, include_software=False, include_net_quality=False):
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

    if include_net_quality:
        try:
            quality = get_network_quality()
            if quality:
                network = {**network, **quality}
        except Exception as e:
            logger.warning(f"Error muestreando calidad de red: {e}")

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

    if gpu:
        payload.update(gpu)

    if include_security:
        try:
            sec = collect_security_snapshot()
            if sec is not None:
                payload["security_snapshot"] = sec
        except Exception as e:
            logger.warning(f"Error recolectando huella de seguridad: {e}")
        try:
            net_sec = get_network_security()
            if net_sec is not None:
                payload["network_security"] = net_sec
        except Exception as e:
            logger.warning(f"Error recolectando seguridad de red: {e}")

    if include_software:
        try:
            software = get_installed_software()
            if software is not None:
                payload["software_inventory"] = software
        except Exception as e:
            logger.warning(f"Error recolectando inventario de software: {e}")

    return payload


def send(payload):
    try:
        data = json.dumps(payload, sort_keys=True).encode()
        headers = {
            "Authorization": f"Token {SENTINEL_TOKEN}",
            "Content-Type":  "application/json",
            "User-Agent":    f"Sentinel XO-Agent/4.1 ({platform.system()})",
        }
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

    logger.info(f"Sentinel XO Agent v4.2 | host={platform.node()} | intervalo={INTERVAL}s")
    logger.info(f"Enviando a: {SENTINEL_API_URL}")

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
    last_software_send = 0.0
    last_netq_send = 0.0

    while True:
        try:
            now = time.monotonic()
            send_security = IS_WINDOWS and (now - last_security_send >= SECURITY_INTERVAL)
            send_software = IS_WINDOWS and (now - last_software_send >= SOFTWARE_INTERVAL)
            send_netq = (now - last_netq_send >= NET_QUALITY_INTERVAL)
            payload = collect(include_security=send_security, include_software=send_software,
                              include_net_quality=send_netq)
            send(payload)
            if send_security:
                last_security_send = now
            if send_software:
                last_software_send = now
            if send_netq:
                last_netq_send = now
        except Exception as e:
            logger.error(f"Error inesperado: {e}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
