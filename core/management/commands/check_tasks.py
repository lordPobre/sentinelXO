"""
Sentinel XO — audita el estado de las tareas periódicas de Celery Beat.

Muestra, por cada tarea registrada: si está activa, su horario, cuándo corrió
por última vez y cuántas veces. Sirve para verificar de un vistazo que el beat
está disparando y el worker ejecutando, sin pelear con one-liners en la shell.

Uso:
    python manage.py check_tasks
"""
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Muestra el estado de las tareas periódicas (activas, horario, última ejecución)."

    def handle(self, *args, **options):
        from django_celery_beat.models import PeriodicTask

        tasks = PeriodicTask.objects.all().order_by("task")
        if not tasks:
            self.stdout.write(self.style.WARNING("No hay tareas periódicas registradas."))
            self.stdout.write("Ejecuta: python manage.py setup_periodic_tasks")
            return

        now = timezone.now()
        activas = 0
        nunca = 0

        self.stdout.write("")
        self.stdout.write(f"{'Estado':<7} {'Tarea':<40} {'Horario':<22} {'Última ejecución':<22} {'Veces'}")
        self.stdout.write("-" * 110)

        for t in tasks:
            # Horario legible
            if t.interval:
                horario = f"cada {t.interval.every} {t.interval.period}"
            elif t.crontab:
                c = t.crontab
                horario = f"cron {c.minute} {c.hour} {c.day_of_week} {c.day_of_month}"
            else:
                horario = "(sin horario)"

            # Última ejecución
            if t.last_run_at:
                delta = now - t.last_run_at
                mins = int(delta.total_seconds() // 60)
                if mins < 60:
                    ultima = f"hace {mins} min"
                elif mins < 1440:
                    ultima = f"hace {mins // 60} h"
                else:
                    ultima = f"hace {mins // 1440} d"
            else:
                ultima = "NUNCA"
                nunca += 1

            estado = "OK" if t.enabled else "OFF"
            if t.enabled:
                activas += 1

            # Color según estado
            line = f"{estado:<7} {t.task:<40} {horario:<22} {ultima:<22} {t.total_run_count}"
            if not t.enabled:
                self.stdout.write(self.style.WARNING(line))
            elif t.last_run_at is None and t.crontab is None:
                # Intervalo activo pero nunca corrió: sospechoso
                self.stdout.write(self.style.ERROR(line))
            else:
                self.stdout.write(self.style.SUCCESS(line))

        self.stdout.write("-" * 110)
        self.stdout.write(
            f"Total: {tasks.count()} tarea(s) | {activas} activa(s) | {nunca} sin ejecutar todavía"
        )
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO(
            "Nota: una tarea de intervalo (ej. cada 5 min) que diga NUNCA y lleve rato "
            "registrada indica que el beat/worker no la está procesando. Las de crontab "
            "(diarias/semanales) pueden decir NUNCA si su horario aún no ha llegado."
        ))
