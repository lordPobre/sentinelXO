import uuid
import secrets
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Client(models.Model):
    """Empresa cliente de Sentinel XO."""
    PLAN_CHOICES = [
        ("basic", "Basic"),
        ("professional", "Professional"),
        ("enterprise", "Enterprise"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_name = models.CharField("Empresa", max_length=200)
    rut = models.CharField("RUT", max_length=12, unique=True, blank=True, default="")
    contact_name = models.CharField("Contacto principal", max_length=200, blank=True)
    contact_email = models.EmailField("Email de contacto")
    contact_phone = models.CharField("Teléfono", max_length=20, blank=True)
    plan = models.CharField("Plan", max_length=20, choices=PLAN_CHOICES, default="basic")
    is_active = models.BooleanField("Activo", default=True)
    notes = models.TextField("Notas internas", blank=True)
    alert_emails = models.TextField(
        "Emails adicionales para alertas",
        blank=True,
        help_text="Un email por línea. Recibirán todas las alertas y verificaciones del cliente."
    )
    notify_incidents_only = models.BooleanField(
        "Solo notificar incidentes manuales",
        default=False,
        help_text="Si está activo, solo se envían emails al crear/resolver incidentes. "
                  "Las alertas automáticas (CPU, RAM, temperatura, SMTP) no envían email."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Usuarios del lado cliente que pueden ver su dashboard
    portal_users = models.ManyToManyField(
        User, related_name="client_portals", blank=True,
        verbose_name="Usuarios del portal"
    )

    class Meta:
        verbose_name = "Cliente"
        verbose_name_plural = "Clientes"

    def get_alert_recipients(self) -> list:
        """Retorna todos los emails que deben recibir alertas de este cliente."""
        recipients = []
        if self.contact_email:
            recipients.append(self.contact_email)
        if self.alert_emails:
            for email in self.alert_emails.splitlines():
                email = email.strip()
                if email and "@" in email and email not in recipients:
                    recipients.append(email)
        return recipients
        ordering = ["company_name"]

    def __str__(self):
        return self.company_name

    def get_health_status(self):
        """Devuelve 'ok', 'warning' o 'critical' según el estado general."""
        devices = self.devices.filter(is_active=True)
        if not devices.exists():
            return "unknown"
        offline = sum(1 for d in devices if not d.is_online)
        if offline == 0:
            return "ok"
        elif offline < devices.count():
            return "warning"
        return "critical"


class HardwareDevice(models.Model):
    """Equipo físico o virtual monitorizado en la red del cliente."""
    DEVICE_TYPES = [
        ("workstation", "Workstation"),
        ("server", "Servidor"),
        ("laptop", "Laptop"),
        ("printer", "Impresora"),
        ("network", "Equipo de Red"),
        ("other", "Otro"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="devices",
                               verbose_name="Cliente")
    hostname = models.CharField("Nombre del equipo", max_length=200)
    friendly_name = models.CharField("Nombre amigable", max_length=200, blank=True)
    agent_token = models.CharField("Token del agente", max_length=64, unique=True, editable=False)
    device_type = models.CharField("Tipo", max_length=20, choices=DEVICE_TYPES, default="workstation")
    os = models.CharField("Sistema operativo", max_length=100, blank=True)
    os_version = models.CharField("Versión SO", max_length=200, blank=True)
    ip_address = models.GenericIPAddressField("IP local", null=True, blank=True)
    is_active = models.BooleanField("Activo", default=True)
    last_seen = models.DateTimeField("Último contacto", null=True, blank=True)
    registered_at = models.DateTimeField("Registrado", auto_now_add=True)

    class Meta:
        verbose_name = "Dispositivo"
        verbose_name_plural = "Dispositivos"
        ordering = ["client", "hostname"]

    def save(self, *args, **kwargs):
        if not self.agent_token:
            self.agent_token = secrets.token_hex(32)
        super().save(*args, **kwargs)

    def __str__(self):
        name = self.friendly_name or self.hostname
        return f"{name} ({self.client})"

    @property
    def display_name(self):
        return self.friendly_name or self.hostname

    @property
    def is_online(self) -> bool:
        if not self.last_seen:
            return False
        return (timezone.now() - self.last_seen).total_seconds() < 1800  # 30 min

    @property
    def status(self):
        if not self.last_seen:
            return "never"
        if self.is_online:
            latest = self.snapshots.first()
            if latest:
                if latest.ram_used_percent > 90 or latest.cpu_percent > 95:
                    return "warning"
                if any(d.get("used_percent", 0) > 90 for d in (latest.disk_usage or [])):
                    return "warning"
            return "online"
        return "offline"


class TelemetrySnapshot(models.Model):
    """Captura de estado del equipo enviada por el agente."""
    device = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE,
                               related_name="snapshots")
    captured_at = models.DateTimeField("Capturado")
    cpu_percent = models.FloatField("CPU %", default=0)
    ram_used_percent = models.FloatField("RAM %", default=0)
    ram_total_gb = models.FloatField("RAM total (GB)", default=0)
    disk_usage = models.JSONField("Discos", default=list)
    uptime_seconds = models.BigIntegerField("Uptime (s)", default=0)
    temperatures   = models.JSONField("Temperaturas", default=list)
    network        = models.JSONField("Red", default=dict)
    cpu_freq_mhz   = models.FloatField("CPU Freq (MHz)", null=True, blank=True)
    cpu_cores      = models.IntegerField("Núcleos físicos", null=True, blank=True)
    cpu_threads    = models.IntegerField("Hilos lógicos", null=True, blank=True)
    # GPU (opcional — solo si el equipo tiene GPU detectable)
    gpu_name                = models.CharField("GPU", max_length=200, blank=True, default="")
    gpu_usage_percent       = models.FloatField("GPU %", null=True, blank=True)
    gpu_memory_used_percent = models.FloatField("VRAM %", null=True, blank=True)
    gpu_memory_total_gb     = models.FloatField("VRAM total (GB)", null=True, blank=True)
    gpu_temp_celsius        = models.FloatField("Temp GPU (°C)", null=True, blank=True)

    class Meta:
        ordering = ["-captured_at"]
        indexes = [
            models.Index(fields=["device", "-captured_at"]),
            models.Index(fields=["-captured_at"]),
        ]
        get_latest_by = "captured_at"

    def __str__(self):
        return f"{self.device.hostname} @ {self.captured_at:%Y-%m-%d %H:%M}"

    @property
    def uptime_human(self):
        s = self.uptime_seconds
        d, s = divmod(s, 86400)
        h, s = divmod(s, 3600)
        m, _ = divmod(s, 60)
        if d:
            return f"{d}d {h}h"
        return f"{h}h {m}m"


class Domain(models.Model):
    """Dominio web administrado para el cliente."""
    STATUS_CHOICES = [
        ("ok", "OK"),
        ("warning", "Por vencer (< 90 días)"),
        ("critical", "Crítico (< 30 días)"),
        ("expired", "Vencido"),
        ("unknown", "Desconocido"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="domains",
                               verbose_name="Cliente")
    fqdn = models.CharField("Dominio", max_length=253)
    registrar = models.CharField("Registrador", max_length=200, blank=True)
    expiry_date = models.DateField("Fecha de vencimiento", null=True, blank=True)
    auto_renew = models.BooleanField("Renovación automática", default=False)
    last_checked = models.DateTimeField("Última verificación", null=True, blank=True)
    status = models.CharField("Estado", max_length=20, choices=STATUS_CHOICES, default="unknown")
    resolves_dns = models.BooleanField("Resuelve DNS", default=True)
    notes = models.TextField("Notas", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # Certificado SSL
    ssl_expiry_date  = models.DateField("Vencimiento SSL", null=True, blank=True)
    ssl_issuer       = models.CharField("Emisor SSL", max_length=200, blank=True)
    ssl_status       = models.CharField("Estado SSL", max_length=20,
                                        choices=STATUS_CHOICES, default="unknown")
    ssl_protocol     = models.CharField("Protocolo TLS", max_length=20, blank=True)
    ssl_error        = models.CharField("Error SSL", max_length=300, blank=True)

    class Meta:
        verbose_name = "Dominio"
        verbose_name_plural = "Dominios"
        ordering = ["expiry_date"]
        unique_together = [("client", "fqdn")]

    def __str__(self):
        return self.fqdn

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - timezone.now().date()).days

    @property
    def days_until_ssl_expiry(self):
        if not self.ssl_expiry_date:
            return None
        return (self.ssl_expiry_date - timezone.now().date()).days

    def refresh_ssl_status(self):
        days = self.days_until_ssl_expiry
        if self.ssl_error:
            self.ssl_status = "unknown"
        elif days is None:
            self.ssl_status = "unknown"
        elif days < 0:
            self.ssl_status = "expired"
        elif days < 15:
            self.ssl_status = "critical"
        elif days < 30:
            self.ssl_status = "warning"
        else:
            self.ssl_status = "ok"

    def refresh_status(self):
        days = self.days_until_expiry
        if days is None:
            self.status = "unknown"
        elif days < 0:
            self.status = "expired"
        elif days < 30:
            self.status = "critical"
        elif days < 90:
            self.status = "warning"
        else:
            self.status = "ok"


class M365Tenant(models.Model):
    """Credenciales OAuth para acceder al tenant M365 de un cliente."""
    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name="m365_tenant",
                                  verbose_name="Cliente")
    tenant_id = models.CharField("Tenant ID (Azure AD)", max_length=100)
    azure_client_id = models.CharField("Client ID (App Registration)", max_length=100)
    azure_client_secret = models.CharField("Client Secret", max_length=300)
    last_synced = models.DateTimeField("Última sincronización", null=True, blank=True)
    sync_error = models.TextField("Último error de sync", blank=True)
    is_active = models.BooleanField("Activo", default=True)
    verify_email = models.EmailField(
        "Email de destino para verificación",
        blank=True,
        help_text="Email al que se enviará el test de envío en cada verificación. "
                  "Si está vacío, no se envía el email de prueba."
    )
    sender_mailbox = models.EmailField(
        "Buzón remitente (sendMail)",
        blank=True,
        help_text="Buzón del tenant desde el que se envía el email de verificación. "
                  "Ej: it@vcchile.cl — debe ser un usuario con licencia Exchange activa."
    )

    class Meta:
        verbose_name = "Tenant M365"
        verbose_name_plural = "Tenants M365"

    def __str__(self):
        return f"M365 — {self.client}"


class M365License(models.Model):
    """Pool de licencias Microsoft 365 de un cliente."""
    STATUS_CHOICES = [
        ("Enabled", "Activa"),
        ("Suspended", "Suspendida"),
        ("Warning", "Advertencia"),
        ("LockedOut", "Bloqueada"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="m365_licenses",
                               verbose_name="Cliente")
    sku_part_number = models.CharField("SKU", max_length=100)
    friendly_name = models.CharField("Nombre del producto", max_length=200, blank=True)
    total_licenses = models.IntegerField("Total", default=0)
    consumed_licenses = models.IntegerField("Usadas", default=0)
    capability_status = models.CharField("Estado", max_length=50,
                                         choices=STATUS_CHOICES, default="Enabled")
    last_synced = models.DateTimeField("Última sincronización", null=True, blank=True)

    class Meta:
        verbose_name = "Licencia M365"
        verbose_name_plural = "Licencias M365"
        unique_together = [("client", "sku_part_number")]
        ordering = ["friendly_name"]

    def __str__(self):
        return f"{self.friendly_name or self.sku_part_number} — {self.client}"

    @property
    def available_licenses(self):
        return self.total_licenses - self.consumed_licenses

    @property
    def utilization_percent(self):
        if self.total_licenses == 0:
            return 0.0
        return round((self.consumed_licenses / self.total_licenses) * 100, 1)

    @property
    def utilization_status(self):
        pct = self.utilization_percent
        if pct >= 100:
            return "critical"
        elif pct >= 85:
            return "warning"
        return "ok"


class MaintenanceIncident(models.Model):
    """Incidente o tarea de mantenimiento (visible en el dashboard y reporte mensual)."""
    SEVERITY_CHOICES = [
        ("low", "Baja"),
        ("medium", "Media"),
        ("high", "Alta"),
        ("critical", "Crítica"),
    ]

    CATEGORY_CHOICES = [
        ("hardware",  "Hardware / Equipo"),
        ("domain",    "Dominio"),
        ("email",     "Email / SMTP"),
        ("license",   "Licencia M365"),
        ("network",   "Red"),
        ("other",     "Otro"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="incidents",
                               verbose_name="Cliente")
    device = models.ForeignKey(HardwareDevice, on_delete=models.SET_NULL,
                               null=True, blank=True, related_name="incidents")
    category = models.CharField("Categoría", max_length=20,
                                choices=CATEGORY_CHOICES, default="other")
    title = models.CharField("Título", max_length=300)
    description    = models.TextField("Descripción", blank=True)
    ai_diagnosis   = models.JSONField("Diagnóstico IA", null=True, blank=True,
                                       help_text="Diagnóstico automático generado por Claude al crear el incidente")
    severity = models.CharField("Severidad", max_length=10,
                                choices=SEVERITY_CHOICES, default="medium")
    notify_email = models.BooleanField("Notificar por email", default=True)
    is_resolved = models.BooleanField("Resuelto", default=False)
    resolved_at = models.DateTimeField("Resuelto el", null=True, blank=True)
    created_at = models.DateTimeField("Creado", auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Incidente"
        verbose_name_plural = "Incidentes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title}"

    def resolve(self):
        self.is_resolved = True
        self.resolved_at = timezone.now()
        self.save(update_fields=["is_resolved", "resolved_at", "updated_at"])


class MonthlyReport(models.Model):
    """Registro de reportes PDF generados y enviados."""
    STATUS_CHOICES = [
        ("pending", "Pendiente"),
        ("generating", "Generando"),
        ("ready", "Listo"),
        ("sent", "Enviado"),
        ("error", "Error"),
    ]

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="reports",
                               verbose_name="Cliente")
    period_year = models.IntegerField("Año")
    period_month = models.IntegerField("Mes")
    status = models.CharField("Estado", max_length=20, choices=STATUS_CHOICES, default="pending")
    pdf_file = models.FileField("Archivo PDF", upload_to="reports/%Y/%m/", null=True, blank=True)
    generated_at = models.DateTimeField("Generado", null=True, blank=True)
    sent_at = models.DateTimeField("Enviado", null=True, blank=True)
    error_message = models.TextField("Error", blank=True)
    # Resumen que se almacena en el reporte
    summary_data = models.JSONField("Datos del resumen", default=dict)

    class Meta:
        verbose_name = "Reporte mensual"
        verbose_name_plural = "Reportes mensuales"
        unique_together = [("client", "period_year", "period_month")]
        ordering = ["-period_year", "-period_month"]

    def __str__(self):
        return f"Reporte {self.period_year}/{self.period_month:02d} — {self.client}"

class AlertRule(models.Model):
    """
    Regla de alerta configurable por cliente.
    Define umbrales para CPU, RAM, GPU y temperatura.
    """
    METRIC_CHOICES = [
        ("cpu",       "CPU (%)"),
        ("ram",       "RAM (%)"),
        ("gpu_usage", "GPU Uso (%)"),
        ("gpu_mem",   "GPU Memoria (%)"),
        ("cpu_temp",  "Temperatura CPU (°C)"),
        ("gpu_temp",  "Temperatura GPU (°C)"),
    ]
    SEVERITY_CHOICES = [
        ("warning",  "Advertencia"),
        ("critical", "Crítica"),
    ]

    client      = models.ForeignKey("Client", on_delete=models.CASCADE,
                                    related_name="alert_rules", verbose_name="Cliente")
    device      = models.ForeignKey("HardwareDevice", on_delete=models.CASCADE,
                                    null=True, blank=True, related_name="alert_rules",
                                    verbose_name="Dispositivo (vacío = todos)")
    metric      = models.CharField("Métrica", max_length=20, choices=METRIC_CHOICES)
    threshold   = models.FloatField("Umbral")
    severity    = models.CharField("Severidad", max_length=10,
                                   choices=SEVERITY_CHOICES, default="warning")
    is_active   = models.BooleanField("Activa", default=True)
    cooldown_minutes = models.PositiveIntegerField(
        "Cooldown (min)", default=30,
        help_text="Minutos mínimos entre alertas repetidas del mismo tipo")
    notify_email = models.BooleanField("Notificar por email", default=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Regla de alerta"
        verbose_name_plural = "Reglas de alerta"
        ordering = ["client", "metric"]

    def __str__(self):
        dev = f" [{self.device.display_name}]" if self.device else " [todos]"
        return f"{self.client}{dev} — {self.get_metric_display()} > {self.threshold}"


class AlertEvent(models.Model):
    """
    Registro de una alerta disparada. Usado para cooldown y auditoría.
    """
    STATUS_CHOICES = [
        ("firing",    "Activa"),
        ("resolved",  "Resuelta"),
        ("silenced",  "Silenciada"),
    ]

    rule        = models.ForeignKey(AlertRule, on_delete=models.CASCADE,
                                    related_name="events", verbose_name="Regla")
    device      = models.ForeignKey("HardwareDevice", on_delete=models.CASCADE,
                                    related_name="alert_events", verbose_name="Dispositivo")
    metric      = models.CharField("Métrica", max_length=20)
    value       = models.FloatField("Valor medido")
    threshold   = models.FloatField("Umbral")
    severity    = models.CharField("Severidad", max_length=10)
    status      = models.CharField("Estado", max_length=10,
                                   choices=STATUS_CHOICES, default="firing")
    notified    = models.BooleanField("Email enviado", default=False)
    fired_at    = models.DateTimeField("Disparada", auto_now_add=True)
    resolved_at = models.DateTimeField("Resuelta", null=True, blank=True)
    message     = models.CharField("Mensaje", max_length=300, blank=True)

    class Meta:
        verbose_name = "Evento de alerta"
        verbose_name_plural = "Eventos de alerta"
        ordering = ["-fired_at"]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.device} — {self.metric}={self.value} @ {self.fired_at:%d/%m %H:%M}"


class SecurityCheck(models.Model):
    """Snapshot de postura de seguridad M365 de un cliente (Secure Score, MFA, etc)."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="security_checks",
                               verbose_name="Cliente")
    checked_at = models.DateTimeField("Verificado", auto_now_add=True)

    # Secure Score (Microsoft)
    secure_score        = models.FloatField("Secure Score", null=True, blank=True)
    secure_score_max    = models.FloatField("Secure Score máximo", null=True, blank=True)

    # MFA
    mfa_registered      = models.IntegerField("Usuarios con MFA", null=True, blank=True)
    mfa_total           = models.IntegerField("Usuarios totales", null=True, blank=True)

    # Detalle / errores
    check_details = models.JSONField("Detalle", default=dict, blank=True)
    error_msg     = models.TextField("Error", blank=True)
    ai_summary    = models.JSONField("Análisis IA", null=True, blank=True,
                                     help_text="Reporte de seguridad narrativo generado por Claude")

    class Meta:
        verbose_name = "Chequeo de seguridad"
        verbose_name_plural = "Chequeos de seguridad"
        ordering = ["-checked_at"]

    def __str__(self):
        return f"Seguridad {self.client} @ {self.checked_at:%d/%m %H:%M}"

    @property
    def secure_score_percent(self):
        if self.secure_score is None or not self.secure_score_max:
            return None
        return round((self.secure_score / self.secure_score_max) * 100, 1)

    @property
    def mfa_percent(self):
        if self.mfa_registered is None or not self.mfa_total:
            return None
        return round((self.mfa_registered / self.mfa_total) * 100, 1)

class SecuritySnapshot(models.Model):
    """Última huella de seguridad conocida de un dispositivo (para comparar y detectar cambios)."""

    device = models.OneToOneField(HardwareDevice, on_delete=models.CASCADE,
                                   related_name="security_snapshot", verbose_name="Dispositivo")
    local_admins      = models.JSONField("Administradores locales", default=list, blank=True)
    startup_programs  = models.JSONField("Programas de inicio", default=list, blank=True)
    scheduled_tasks   = models.JSONField("Tareas programadas", default=list, blank=True)
    updated_at        = models.DateTimeField("Actualizado", auto_now=True)

    class Meta:
        verbose_name = "Huella de seguridad"
        verbose_name_plural = "Huellas de seguridad"

    def __str__(self):
        return f"Huella de seguridad — {self.device}"


class SecurityAnomalyEvent(models.Model):
    """Cambio detectado en la huella de seguridad de un dispositivo (posible indicador de compromiso)."""

    TYPE_CHOICES = [
        ("new_admin",      "Nuevo administrador local"),
        ("removed_admin",  "Administrador local eliminado"),
        ("new_startup",    "Nuevo programa de inicio"),
        ("removed_startup","Programa de inicio eliminado"),
        ("new_task",       "Nueva tarea programada"),
        ("removed_task",   "Tarea programada eliminada"),
    ]
    SEVERITY_CHOICES = [
        ("info",     "Informativa"),
        ("warning",  "Advertencia"),
        ("critical", "Crítica"),
    ]
    STATUS_CHOICES = [
        ("open",         "Abierta"),
        ("acknowledged", "Revisada"),
    ]

    device      = models.ForeignKey(HardwareDevice, on_delete=models.CASCADE,
                                    related_name="security_anomalies", verbose_name="Dispositivo")
    anomaly_type = models.CharField("Tipo", max_length=20, choices=TYPE_CHOICES)
    severity    = models.CharField("Severidad", max_length=10, choices=SEVERITY_CHOICES, default="warning")
    status      = models.CharField("Estado", max_length=12, choices=STATUS_CHOICES, default="open")
    detail      = models.CharField("Detalle", max_length=300)
    detected_at = models.DateTimeField("Detectada", auto_now_add=True)
    notified    = models.BooleanField("Email enviado", default=False)
    ai_diagnosis = models.JSONField("Diagnóstico IA", null=True, blank=True)

    class Meta:
        verbose_name = "Anomalía de seguridad"
        verbose_name_plural = "Anomalías de seguridad"
        ordering = ["-detected_at"]

    def __str__(self):
        return f"[{self.severity.upper()}] {self.device} — {self.get_anomaly_type_display()}: {self.detail[:50]}"

    @property
    def detail_summary(self):
        """Parte descriptiva del detalle (antes de '→'), sin la ruta/comando técnico."""
        if "→" in self.detail:
            return self.detail.split("→", 1)[0].strip()
        return self.detail

    @property
    def detail_code(self):
        """Parte técnica del detalle (ruta, comando, clave de registro), si existe."""
        if "→" in self.detail:
            return self.detail.split("→", 1)[1].strip()
        return None