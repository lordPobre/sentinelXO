from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_signin_monitoring"),
    ]

    operations = [
        migrations.AlterField(
            model_name="securityanomalyevent",
            name="anomaly_type",
            field=models.CharField(choices=[
                ("new_admin", "Nuevo administrador local"),
                ("removed_admin", "Administrador local eliminado"),
                ("new_startup", "Nuevo programa de inicio"),
                ("removed_startup", "Programa de inicio eliminado"),
                ("new_task", "Nueva tarea programada"),
                ("removed_task", "Tarea programada eliminada"),
                ("new_software", "Nuevo software instalado"),
                ("removed_software", "Software desinstalado"),
            ], max_length=20, verbose_name="Tipo"),
        ),
        migrations.CreateModel(
            name="SoftwareSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("software_list", models.JSONField(blank=True, default=list, verbose_name="Software instalado")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Actualizado")),
                ("cve_analysis", models.JSONField(blank=True, null=True, verbose_name="Análisis CVE (IA)")),
                ("cve_checked_at", models.DateTimeField(blank=True, null=True, verbose_name="Análisis CVE generado")),
                ("device", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                    related_name="software_snapshot", to="core.hardwaredevice", verbose_name="Dispositivo")),
            ],
            options={
                "verbose_name": "Inventario de software",
                "verbose_name_plural": "Inventarios de software",
            },
        ),
    ]
