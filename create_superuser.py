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
    user, created = User.objects.get_or_create(username=username)
    user.set_password(password)
    user.is_superuser = True
    user.is_staff = True
    user.email = email
    user.save()
    print(f"Superuser '{username}' {'creado' if created else 'actualizado'} correctamente.")
