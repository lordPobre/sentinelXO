from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_telemetrysnapshot_gpu_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="AlertRule",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("metric", models.CharField(choices=[
                    ("cpu","CPU (%)"),("ram","RAM (%)"),("gpu_usage","GPU Uso (%)"),
                    ("gpu_mem","GPU Memoria (%)"),("cpu_temp","Temperatura CPU (°C)"),
                    ("gpu_temp","Temperatura GPU (°C)")], max_length=20, verbose_name="Métrica")),
                ("threshold", models.FloatField(verbose_name="Umbral")),
                ("severity", models.CharField(choices=[("warning","Advertencia"),("critical","Crítica")],
                    default="warning", max_length=10, verbose_name="Severidad")),
                ("is_active", models.BooleanField(default=True, verbose_name="Activa")),
                ("cooldown_minutes", models.PositiveIntegerField(default=30,
                    help_text="Minutos mínimos entre alertas repetidas del mismo tipo",
                    verbose_name="Cooldown (min)")),
                ("notify_email", models.BooleanField(default=True, verbose_name="Notificar por email")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="alert_rules", to="core.client", verbose_name="Cliente")),
                ("device", models.ForeignKey(blank=True, null=True,
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="alert_rules", to="core.hardwaredevice",
                    verbose_name="Dispositivo (vacío = todos)")),
            ],
            options={"verbose_name": "Regla de alerta", "verbose_name_plural": "Reglas de alerta",
                     "ordering": ["client", "metric"]},
        ),
        migrations.CreateModel(
            name="AlertEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("metric", models.CharField(max_length=20, verbose_name="Métrica")),
                ("value", models.FloatField(verbose_name="Valor medido")),
                ("threshold", models.FloatField(verbose_name="Umbral")),
                ("severity", models.CharField(max_length=10, verbose_name="Severidad")),
                ("status", models.CharField(choices=[("firing","Activa"),("resolved","Resuelta"),
                    ("silenced","Silenciada")], default="firing", max_length=10, verbose_name="Estado")),
                ("notified", models.BooleanField(default=False, verbose_name="Email enviado")),
                ("fired_at", models.DateTimeField(auto_now_add=True, verbose_name="Disparada")),
                ("resolved_at", models.DateTimeField(blank=True, null=True, verbose_name="Resuelta")),
                ("message", models.CharField(blank=True, max_length=300, verbose_name="Mensaje")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="alert_events", to="core.hardwaredevice",
                    verbose_name="Dispositivo")),
                ("rule", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="events", to="core.alertrule", verbose_name="Regla")),
            ],
            options={"verbose_name": "Evento de alerta", "verbose_name_plural": "Eventos de alerta",
                     "ordering": ["-fired_at"]},
        ),
    ]
