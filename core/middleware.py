"""
Sentinel XO — Middlewares personalizados
"""


class TOTPMiddleware:
    """
    Si el usuario está autenticado y tiene 2FA activo, verifica que
    haya pasado el segundo factor en esta sesión. Si no, redirige
    a la página de verificación TOTP.
    """
    EXEMPT_PATHS = (
        "/auth/",
        "/totp/",
        "/admin/",
        "/api/",
        "/health/",
        "/static/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.user.is_authenticated
            and not request.session.get("2fa_verified")
            and not any(request.path.startswith(p) for p in self.EXEMPT_PATHS)
        ):
            try:
                totp = request.user.totp
                if totp.is_enabled:
                    from django.shortcuts import redirect
                    return redirect(f"/totp/verify/?next={request.path}")
            except Exception:
                pass

        return self.get_response(request)


class SecurityHeadersMiddleware:
    """
    Agrega headers de seguridad adicionales a todas las respuestas.
    Complementa los settings de Django (SECURE_*, X_FRAME_OPTIONS, etc.).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-Frame-Options"] = "DENY"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none';"
        )
        return response
