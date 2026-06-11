from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_m365tenant_verify_email"),
    ]

    operations = [
        migrations.AddField(
            model_name="m365tenant",
            name="sender_mailbox",
            field=models.EmailField(
                blank=True,
                default="",
                help_text="Buzón del tenant desde el que se envía el email de verificación. Ej: it@vcchile.cl — debe ser un usuario con licencia Exchange activa.",
                verbose_name="Buzón remitente (sendMail)",
            ),
        ),
    ]
