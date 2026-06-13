from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_auditlog"),
    ]

    operations = [
        migrations.AddField(
            model_name="hardwaredevice",
            name="is_offline",
            field=models.BooleanField(default=False, verbose_name="Sin conexión"),
        ),
        migrations.AddField(
            model_name="hardwaredevice",
            name="offline_since",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Sin conexión desde"),
        ),
        migrations.AddField(
            model_name="hardwaredevice",
            name="offline_notified",
            field=models.BooleanField(default=False, verbose_name="Alerta offline enviada"),
        ),
    ]
