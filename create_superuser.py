"""
Script para crear superusuario automáticamente en Railway.
Se ejecuta como parte del preDeployCommand si las variables están definidas.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth.models import User

username = os.environ.get('DJANGO_SUPERUSER_USERNAME')
email    = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')

if not username or not password:
    print("Superuser: variables no definidas, saltando.")
else:
    if User.objects.filter(username=username).exists():
        print(f"Superuser '{username}' ya existe, saltando.")
    else:
        User.objects.create_superuser(username, email, password)
        print(f"Superuser '{username}' creado correctamente.")
