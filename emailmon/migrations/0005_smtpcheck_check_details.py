from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("emailmon", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="smtpcheck",
            name="check_details",
            field=models.JSONField(blank=True, default=dict, verbose_name="Detalle checks"),
        ),
    ]
