import uuid
from django.db import models
from django.utils import timezone


class EmailLog(models.Model):
    """Registro de cada email enviado por el sistema Perseus."""
    STATUS_CHOICES = [
        ("sent",    "Enviado"),
        ("failed",  "Error"),
        ("bounced", "Rebotado"),
    ]
    CATEGORY_CHOICES = [
        ("report",    "Reporte mensual"),
        ("alert",     "Alerta de vencimiento"),
        ("incident",  "Notificación de incidente"),
        ("test",      "Email de prueba"),
        ("other",     "Otro"),
    ]

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recipient   = models.EmailField("Destinatario")
    subject     = models.CharField("Asunto", max_length=500)
    category    = models.CharField("Categoría", max_length=20, choices=CATEGORY_CHOICES, default="other")
    status      = models.CharField("Estado", max_length=10, choices=STATUS_CHOICES, default="sent")
    error_msg   = models.TextField("Error", blank=True)
    sent_at     = models.DateTimeField("Enviado", auto_now_add=True)
    # Referencia opcional al cliente relacionado
    client      = models.ForeignKey(
        "core.Client", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="email_logs"
    )

    class Meta:
        verbose_name = "Email enviado"
        verbose_name_plural = "Emails enviados"
        ordering = ["-sent_at"]
        indexes = [models.Index(fields=["-sent_at"])]

    def __str__(self):
        return f"{self.get_status_display()} → {self.recipient} | {self.subject[:50]}"


class SmtpCheck(models.Model):
    """Resultado de cada verificación de conectividad SMTP."""
    STATUS_CHOICES = [
        ("ok",      "OK"),
        ("timeout", "Timeout"),
        ("error",   "Error"),
    ]

    checked_at    = models.DateTimeField("Verificado", auto_now_add=True)
    status        = models.CharField("Estado", max_length=10, choices=STATUS_CHOICES)
    response_ms   = models.IntegerField("Tiempo de respuesta (ms)", null=True, blank=True)
    error_msg     = models.TextField("Error", blank=True)
    smtp_host     = models.CharField("Host SMTP", max_length=200)
    smtp_port     = models.IntegerField("Puerto SMTP")

    class Meta:
        verbose_name = "Verificación SMTP"
        verbose_name_plural = "Verificaciones SMTP"
        ordering = ["-checked_at"]
        get_latest_by = "checked_at"

    def __str__(self):
        return f"{self.smtp_host}:{self.smtp_port} — {self.get_status_display()} @ {self.checked_at:%Y-%m-%d %H:%M}"
