from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_hardwaredevice_offline_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="maintenanceincident",
            name="category",
            field=models.CharField(
                choices=[
                    ("hardware", "Hardware / Equipo"),
                    ("domain", "Dominio"),
                    ("email", "Email / SMTP"),
                    ("license", "Licencia M365"),
                    ("network", "Red"),
                    ("connectivity", "Conectividad del Agente"),
                    ("other", "Otro"),
                ],
                default="other", max_length=20, verbose_name="Categoría",
            ),
        ),
    ]
