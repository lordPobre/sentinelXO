from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_securitycheck"),
    ]

    operations = [
        migrations.AddField(
            model_name="domain",
            name="ssl_expiry_date",
            field=models.DateField(blank=True, null=True, verbose_name="Vencimiento SSL"),
        ),
        migrations.AddField(
            model_name="domain",
            name="ssl_issuer",
            field=models.CharField(blank=True, max_length=200, verbose_name="Emisor SSL"),
        ),
        migrations.AddField(
            model_name="domain",
            name="ssl_status",
            field=models.CharField(
                choices=[("ok", "OK"), ("warning", "Por vencer (< 90 días)"),
                         ("critical", "Crítico (< 30 días)"), ("expired", "Vencido"),
                         ("unknown", "Desconocido")],
                default="unknown", max_length=20, verbose_name="Estado SSL",
            ),
        ),
        migrations.AddField(
            model_name="domain",
            name="ssl_protocol",
            field=models.CharField(blank=True, max_length=20, verbose_name="Protocolo TLS"),
        ),
        migrations.AddField(
            model_name="domain",
            name="ssl_error",
            field=models.CharField(blank=True, max_length=300, verbose_name="Error SSL"),
        ),
    ]
