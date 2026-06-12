from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_maintenanceincident_ai_diagnosis"),
    ]

    operations = [
        migrations.CreateModel(
            name="SecurityCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("checked_at", models.DateTimeField(auto_now_add=True, verbose_name="Verificado")),
                ("secure_score", models.FloatField(blank=True, null=True, verbose_name="Secure Score")),
                ("secure_score_max", models.FloatField(blank=True, null=True, verbose_name="Secure Score máximo")),
                ("mfa_registered", models.IntegerField(blank=True, null=True, verbose_name="Usuarios con MFA")),
                ("mfa_total", models.IntegerField(blank=True, null=True, verbose_name="Usuarios totales")),
                ("check_details", models.JSONField(blank=True, default=dict, verbose_name="Detalle")),
                ("error_msg", models.TextField(blank=True, verbose_name="Error")),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="security_checks", to="core.client", verbose_name="Cliente")),
            ],
            options={
                "verbose_name": "Chequeo de seguridad",
                "verbose_name_plural": "Chequeos de seguridad",
                "ordering": ["-checked_at"],
            },
        ),
    ]
