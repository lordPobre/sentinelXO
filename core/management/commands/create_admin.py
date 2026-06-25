from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
import os

class Command(BaseCommand):
    help = 'Crea el superusuario desde variables de entorno (idempotente, sin romper sesiones)'

    def handle(self, *args, **kwargs):
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '')
        email    = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
        force    = os.environ.get('DJANGO_SUPERUSER_FORCE_RESET', 'False') == 'True'

        user, created = User.objects.get_or_create(
            username=username,
            defaults={'email': email, 'is_staff': True, 'is_superuser': True},
        )

        if created:
            if not password:
                self.stderr.write(self.style.WARNING(
                    "DJANGO_SUPERUSER_PASSWORD vacía — admin creado SIN contraseña utilizable."
                ))
            else:
                user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' creado."))
        elif force and password:
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            self.stdout.write(self.style.WARNING(f"Superuser '{username}': contraseña reseteada (force)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Superuser '{username}' ya existe — sin cambios."))