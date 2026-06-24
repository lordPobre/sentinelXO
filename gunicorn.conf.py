"""
Gunicorn — configuración de producción (Sentinel XO / Railway)
==============================================================
Objetivo principal: ocultar el fingerprint del servidor (cabecera `Server:`
que delata "gunicorn/<versión>") y fijar una config de producción sensata.

Uso (Procfile / startCommand del servicio WEB en Railway):
    gunicorn config.wsgi:application -c gunicorn.conf.py --bind 0.0.0.0:$PORT

Debe vivir en la RAÍZ del repo (junto a manage.py), que es el directorio de
trabajo del contenedor (/app).
"""
import os

# ── Ocultar versión del servidor ────────────────────────────────────────────
# Gunicorn expone "Server: gunicorn/XX.X" en cada respuesta. Reescribimos el
# software del servidor para no revelar el producto ni la versión.
import gunicorn
gunicorn.SERVER_SOFTWARE = "Server"
try:
    # En algunas versiones la cabecera se arma desde este módulo:
    import gunicorn.http.wsgi as _wsgi
    _wsgi.SERVER_SOFTWARE = "Server"
except Exception:
    pass

# ── Red / binding ───────────────────────────────────────────────────────────
# Railway inyecta $PORT; si se pasa --bind en el comando, ese gana. Dejamos un
# default coherente por si se omite.
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"

# ── Workers ─────────────────────────────────────────────────────────────────
# Mantengo 2 (como tu Procfile). Si algún día quieres autoescalar por CPU:
#   workers = (os.cpu_count() or 1) * 2 + 1
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
worker_class = "sync"
timeout = 120
graceful_timeout = 30
keepalive = 5

# ── Reciclado de workers (mitiga fugas de memoria en procesos largos) ────────
max_requests = 1000
max_requests_jitter = 100

# ── Logging a stdout/stderr (Railway captura la consola) ─────────────────────
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOGLEVEL", "info")

# Formato de access log SIN exponer detalles innecesarios.
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(L)ss "%(a)s"'

# ── Endurecimiento de límites de cabeceras (defensa básica) ──────────────────
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# ── Hook: reforzar el ocultamiento por si el entorno recarga el módulo ───────
def on_starting(server):
    import gunicorn as _g
    _g.SERVER_SOFTWARE = "Server"
