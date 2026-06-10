from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_client_notify_incidents_only"),
    ]

    operations = [
        migrations.AddField(
            model_name="m365tenant",
            name="verify_email",
            field=models.EmailField(
                blank=True,
                default="",
                help_text="Email al que se enviará el test de envío en cada verificación. Si está vacío, no se envía el email de prueba.",
                verbose_name="Email para verificación sendMail",
            ),
        ),
    ]
