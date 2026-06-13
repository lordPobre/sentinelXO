from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("core", "0014_securitysnapshot_securityanomalyevent"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserTOTP",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("secret", models.CharField(max_length=64, verbose_name="Secreto TOTP")),
                ("is_enabled", models.BooleanField(default=False, verbose_name="2FA activo")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used", models.DateTimeField(blank=True, null=True, verbose_name="Último uso")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,
                    related_name="totp", to="auth.user", verbose_name="Usuario")),
            ],
            options={
                "verbose_name": "Configuración 2FA",
                "verbose_name_plural": "Configuraciones 2FA",
            },
        ),
    ]
