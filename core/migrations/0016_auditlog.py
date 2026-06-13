from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("core", "0015_usertotp"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("username", models.CharField(blank=True, max_length=150, verbose_name="Nombre de usuario")),
                ("action", models.CharField(choices=[
                    ("login","Inicio de sesión"),("logout","Cierre de sesión"),
                    ("2fa_enabled","2FA activado"),("2fa_disabled","2FA desactivado"),
                    ("2fa_verified","2FA verificado"),("client_created","Cliente creado"),
                    ("client_updated","Cliente actualizado"),("incident_created","Incidente creado"),
                    ("incident_resolved","Incidente resuelto"),("report_generated","Reporte generado"),
                    ("anomaly_acked","Anomalía revisada"),("security_check","Verificación de seguridad"),
                    ("other","Otro"),
                ], default="other", max_length=30, verbose_name="Acción")),
                ("resource", models.CharField(blank=True, max_length=200, verbose_name="Recurso")),
                ("detail", models.TextField(blank=True, verbose_name="Detalle")),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True, verbose_name="IP")),
                ("user_agent", models.CharField(blank=True, max_length=300, verbose_name="User Agent")),
                ("timestamp", models.DateTimeField(auto_now_add=True, verbose_name="Fecha/hora")),
                ("success", models.BooleanField(default=True, verbose_name="Exitoso")),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="audit_logs", to="auth.user", verbose_name="Usuario")),
            ],
            options={
                "verbose_name": "Registro de auditoría",
                "verbose_name_plural": "Registros de auditoría",
                "ordering": ["-timestamp"],
                "indexes": [models.Index(fields=["-timestamp"], name="core_audit_timestamp_idx")],
            },
        ),
    ]
