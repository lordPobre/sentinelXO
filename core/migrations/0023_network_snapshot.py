import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_alter_client_options_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='NetworkSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('latency_ms', models.FloatField(blank=True, null=True, verbose_name='Latencia (ms)')),
                ('packet_loss_percent', models.FloatField(blank=True, null=True, verbose_name='Pérdida de paquetes (%)')),
                ('wifi_ssid', models.CharField(blank=True, default='', max_length=200, verbose_name='Red WiFi (SSID)')),
                ('wifi_signal_percent', models.IntegerField(blank=True, null=True, verbose_name='Señal WiFi (%)')),
                ('wifi_encryption', models.CharField(blank=True, default='', max_length=100, verbose_name='Cifrado WiFi')),
                ('network_category', models.CharField(blank=True, default='', max_length=50, verbose_name='Perfil de red')),
                ('firewall', models.JSONField(blank=True, default=list, verbose_name='Estado del firewall')),
                ('dns_servers', models.JSONField(blank=True, default=list, verbose_name='Servidores DNS')),
                ('risk_level', models.CharField(choices=[('ok', 'Segura'), ('warning', 'Advertencia'), ('critical', 'Crítica'), ('unknown', 'Desconocida')], default='unknown', max_length=10, verbose_name='Nivel de riesgo')),
                ('risk_reasons', models.JSONField(blank=True, default=list, verbose_name='Motivos de riesgo')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Actualizado')),
                ('security_checked_at', models.DateTimeField(blank=True, null=True, verbose_name='Seguridad de red evaluada')),
                ('device', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='network_snapshot', to='core.hardwaredevice', verbose_name='Dispositivo')),
            ],
            options={
                'verbose_name': 'Postura de red',
                'verbose_name_plural': 'Posturas de red',
            },
        ),
    ]
