from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_software_inventory"),
    ]

    operations = [
        migrations.AddField(
            model_name="client",
            name="telegram_chat_id",
            field=models.CharField(blank=True, max_length=64, verbose_name="Chat ID de Telegram"),
        ),
    ]
