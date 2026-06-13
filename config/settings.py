import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-key-change-in-production")
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost 127.0.0.1").split()

# Railway — agregar dominio público y healthcheck automáticamente
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
if RAILWAY_PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)
    CSRF_TRUSTED_ORIGINS = [f"https://{RAILWAY_PUBLIC_DOMAIN}"]
else:
    CSRF_TRUSTED_ORIGINS = os.environ.get("CSRF_TRUSTED_ORIGINS", "").split()

# Railway usa este host para verificar el healthcheck
ALLOWED_HOSTS.append("healthcheck.railway.app")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Terceros
    "rest_framework",
    "rest_framework.authtoken",
    "django_celery_beat",
    # Sentinel XO apps
    "core",
    "monitoring",
    "reports",
    "dashboard",
    "emailmon",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.TOTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.perseus_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Base de datos ---
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///db.sqlite3")
if DATABASE_URL.startswith("sqlite"):
    db_path = DATABASE_URL.replace("sqlite:///", "")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / db_path,
        }
    }
else:
    import dj_database_url
    DATABASES = {"default": dj_database_url.config(default=DATABASE_URL)}

# --- Auth ---
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "/auth/login/"
LOGIN_REDIRECT_URL = "/dashboard/"
LOGOUT_REDIRECT_URL = "/auth/login/"

# --- Internacionalización ---
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos ---
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# Solo incluir static/ si existe (evita warning en producción)
_static_dir = BASE_DIR / "static"
STATICFILES_DIRS = [_static_dir] if _static_dir.exists() else []
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon":      "100/day",
        "user":      "1000/day",
        "telemetry": "720/hour",   # 1 req cada 5s por agente = 720/hora máximo
        "login":     "10/minute",  # anti-fuerza-bruta en login
    },
}

# --- Celery ---
# Claude API — usado para análisis predictivo, diagnóstico de incidentes y reportes narrativos
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# --- Email ---
# Email — usa Brevo API HTTP (sin SMTP, compatible con Railway plan Hobby)
EMAIL_BACKEND   = "django.core.mail.backends.dummy.EmailBackend"  # django.core.mail no se usa
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "soporte@perseustechnology.dev")
RESEND_API_KEY  = os.environ.get("RESEND_API_KEY", "")

# --- Brevo ---
BREVO_WEBHOOK_SECRET = os.environ.get("BREVO_WEBHOOK_SECRET", "")  # Clave para verificar webhooks

# --- Sentinel XO config ---
SENTINEL_COMPANY_NAME  = os.environ.get("SENTINEL_COMPANY_NAME", "Sentinel XO")
SENTINEL_SUPPORT_EMAIL = os.environ.get("SENTINEL_SUPPORT_EMAIL", "soporte@sentinelxo.dev")
SENTINEL_HMAC_SECRET   = os.environ.get("SENTINEL_HMAC_SECRET", "")  # si vacío, la validación HMAC se omite
SENTINEL_BACKUP_EMAIL  = os.environ.get("SENTINEL_BACKUP_EMAIL", "")  # destino del backup semanal de la BD
SENTINEL_TELEGRAM_BOT_TOKEN = os.environ.get("SENTINEL_TELEGRAM_BOT_TOKEN", "")  # bot único, un chat_id por cliente

# ── Seguridad HTTP ──────────────────────────────────────────────────────────
SECURE_CONTENT_TYPE_NOSNIFF      = True        # X-Content-Type-Options: nosniff
SECURE_BROWSER_XSS_FILTER        = True        # X-XSS-Protection (legacy browsers)
X_FRAME_OPTIONS                  = "DENY"      # X-Frame-Options: DENY (anti-clickjacking)
SECURE_REFERRER_POLICY           = "strict-origin-when-cross-origin"

# HTTPS — activar en producción (Railway usa HTTPS por defecto)
# Railway usa proxy inverso — siempre confiar en X-Forwarded-Proto
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SECURE_SSL_REDIRECT          = True
    SECURE_REDIRECT_EXEMPT       = [r"^health/$"]  # Railway healthcheck va por HTTP interno
    SESSION_COOKIE_SECURE        = True
    CSRF_COOKIE_SECURE           = True
    SECURE_HSTS_SECONDS          = 31536000    # 1 año
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD          = True

# Sesión — expirar en 8 horas de inactividad
SESSION_COOKIE_AGE               = 28800       # 8 horas en segundos
SESSION_EXPIRE_AT_BROWSER_CLOSE  = False
SESSION_COOKIE_HTTPONLY          = True
SESSION_COOKIE_SAMESITE          = "Lax"

# --- Logging básico ---
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "[{levelname}] {asctime} {module}: {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "perseus": {"handlers": ["console"], "level": "DEBUG" if DEBUG else "INFO", "propagate": False},
    },
}
