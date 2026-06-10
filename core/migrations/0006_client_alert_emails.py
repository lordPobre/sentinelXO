from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_alertrule_alertevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="alert_emails",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Un email por línea. Recibirán todas las alertas y verificaciones del cliente.",
                verbose_name="Emails adicionales para alertas",
            ),
        ),
    ]
