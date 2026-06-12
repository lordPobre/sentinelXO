from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_securitycheck_ai_summary"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecuritySnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("local_admins", models.JSONField(blank=True, default=list, verbose_name="Administradores locales")),
                ("startup_programs", models.JSONField(blank=True, default=list, verbose_name="Programas de inicio")),
                ("scheduled_tasks", models.JSONField(blank=True, default=list, verbose_name="Tareas programadas")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Actualizado")),
                ("device", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="security_snapshot", to="core.hardwaredevice", verbose_name="Dispositivo")),
            ],
            options={
                "verbose_name": "Huella de seguridad",
                "verbose_name_plural": "Huellas de seguridad",
            },
        ),
        migrations.CreateModel(
            name="SecurityAnomalyEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anomaly_type", models.CharField(choices=[
                    ("new_admin", "Nuevo administrador local"),
                    ("removed_admin", "Administrador local eliminado"),
                    ("new_startup", "Nuevo programa de inicio"),
                    ("removed_startup", "Programa de inicio eliminado"),
                    ("new_task", "Nueva tarea programada"),
                    ("removed_task", "Tarea programada eliminada"),
                ], max_length=20, verbose_name="Tipo")),
                ("severity", models.CharField(choices=[
                    ("info", "Informativa"), ("warning", "Advertencia"), ("critical", "Crítica"),
                ], default="warning", max_length=10, verbose_name="Severidad")),
                ("status", models.CharField(choices=[
                    ("open", "Abierta"), ("acknowledged", "Revisada"),
                ], default="open", max_length=12, verbose_name="Estado")),
                ("detail", models.CharField(max_length=300, verbose_name="Detalle")),
                ("detected_at", models.DateTimeField(auto_now_add=True, verbose_name="Detectada")),
                ("notified", models.BooleanField(default=False, verbose_name="Email enviado")),
                ("ai_diagnosis", models.JSONField(blank=True, null=True, verbose_name="Diagnóstico IA")),
                ("device", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="security_anomalies", to="core.hardwaredevice", verbose_name="Dispositivo")),
            ],
            options={
                "verbose_name": "Anomalía de seguridad",
                "verbose_name_plural": "Anomalías de seguridad",
                "ordering": ["-detected_at"],
            },
        ),
    ]
