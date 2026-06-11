from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_m365tenant_sender_mailbox"),
    ]

    operations = [
        migrations.AddField(
            model_name="maintenanceincident",
            name="ai_diagnosis",
            field=models.JSONField(
                blank=True, null=True,
                help_text="Diagnóstico automático generado por Claude al crear el incidente",
                verbose_name="Diagnóstico IA",
            ),
        ),
    ]
