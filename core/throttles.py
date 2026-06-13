"""
Sentinel XO — Throttles personalizados para la API.
"""
from rest_framework.throttling import SimpleRateThrottle


class TelemetryRateThrottle(SimpleRateThrottle):
    """
    Rate limit específico para el endpoint de telemetría del agente.
    Usa el agent_token como clave de caché (cada agente tiene su propio bucket).
    Límite: 720 req/hora = 1 req cada 5 segundos, que es el intervalo mínimo del agente.
    """
    scope = "telemetry"

    def get_cache_key(self, request, view):
        auth = request.headers.get("Authorization", "")
        token = auth.split(" ", 1)[1].strip() if auth.startswith("Token ") else "anon"
        return self.cache_format % {
            "scope": self.scope,
            "ident": token[:16],  # primeros 16 chars del token como clave
        }


class LoginRateThrottle(SimpleRateThrottle):
    """
    Rate limit para el login — limita intentos de fuerza bruta.
    10 intentos por minuto por IP.
    """
    scope = "login"

    def get_cache_key(self, request, view):
        # Clave por IP (respetando proxy de Railway)
        ip = (
            request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or request.META.get("REMOTE_ADDR", "")
        )
        return self.cache_format % {"scope": self.scope, "ident": ip}
