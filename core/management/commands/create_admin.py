from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

class Command(BaseCommand):
    help = 'Crea o actualiza el superusuario desde variables de entorno'

    def handle(self, *args, **kwargs):
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
        email    = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')

        user, created = User.objects.get_or_create(username=username)
        user.set_password(password)
        user.is_superuser = True
        user.is_staff = True
        user.email = email
        user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Superuser '{username}' {'creado' if created else 'actualizado'} OK"
            )
        )
