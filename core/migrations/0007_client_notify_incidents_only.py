from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_client_alert_emails"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="notify_incidents_only",
            field=models.BooleanField(
                default=False,
                help_text="Si está activo, solo se envían emails al crear/resolver incidentes. Las alertas automáticas (CPU, RAM, temperatura, SMTP) no envían email.",
                verbose_name="Solo notificar incidentes manuales",
            ),
        ),
    ]
