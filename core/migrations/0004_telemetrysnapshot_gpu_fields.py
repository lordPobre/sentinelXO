from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_maintenanceincident_category_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="telemetrysnapshot",
            name="gpu_name",
            field=models.CharField(blank=True, default="", max_length=200, verbose_name="GPU"),
        ),
        migrations.AddField(
            model_name="telemetrysnapshot",
            name="gpu_usage_percent",
            field=models.FloatField(blank=True, null=True, verbose_name="GPU %"),
        ),
        migrations.AddField(
            model_name="telemetrysnapshot",
            name="gpu_memory_used_percent",
            field=models.FloatField(blank=True, null=True, verbose_name="VRAM %"),
        ),
        migrations.AddField(
            model_name="telemetrysnapshot",
            name="gpu_memory_total_gb",
            field=models.FloatField(blank=True, null=True, verbose_name="VRAM total (GB)"),
        ),
        migrations.AddField(
            model_name="telemetrysnapshot",
            name="gpu_temp_celsius",
            field=models.FloatField(blank=True, null=True, verbose_name="Temp GPU (°C)"),
        ),
    ]
