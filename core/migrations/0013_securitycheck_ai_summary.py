from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_domain_ssl_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="securitycheck",
            name="ai_summary",
            field=models.JSONField(
                blank=True, null=True,
                help_text="Reporte de seguridad narrativo generado por Claude",
                verbose_name="Análisis IA",
            ),
        ),
    ]
