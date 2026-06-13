from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_maintenanceincident_category_connectivity"),
    ]

    operations = [
        migrations.AddField(
            model_name="m365tenant",
            name="known_countries",
            field=models.JSONField(blank=True, default=list, verbose_name="Países conocidos"),
        ),
        migrations.AddField(
            model_name="m365tenant",
            name="last_signin_check",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Última revisión de inicios de sesión"),
        ),
        migrations.CreateModel(
            name="SignInAnomalyEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("anomaly_type", models.CharField(choices=[
                    ("new_country", "Inicio de sesión desde nuevo país"),
                    ("impossible_travel", "Viaje imposible"),
                    ("risky_signin", "Inicio de sesión riesgoso (Microsoft)"),
                ], max_length=20, verbose_name="Tipo")),
                ("severity", models.CharField(choices=[
                    ("info", "Informativa"), ("warning", "Advertencia"), ("critical", "Crítica"),
                ], default="warning", max_length=10, verbose_name="Severidad")),
                ("status", models.CharField(choices=[
                    ("open", "Abierta"), ("acknowledged", "Revisada"),
                ], default="open", max_length=12, verbose_name="Estado")),
                ("detail", models.CharField(max_length=400, verbose_name="Detalle")),
                ("detected_at", models.DateTimeField(auto_now_add=True, verbose_name="Detectada")),
                ("notified", models.BooleanField(default=False, verbose_name="Email enviado")),
                ("client", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                    related_name="signin_anomalies", to="core.client", verbose_name="Cliente")),
            ],
            options={
                "verbose_name": "Anomalía de inicio de sesión",
                "verbose_name_plural": "Anomalías de inicio de sesión",
                "ordering": ["-detected_at"],
            },
        ),
    ]
