"""
Sentinel XO — registra (o actualiza) las tareas periódicas de Celery Beat
en la base de datos (django-celery-beat usa DatabaseScheduler).

Uso:
    python manage.py setup_periodic_tasks

Idempotente: puede ejecutarse en cada deploy sin duplicar entradas.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, CrontabSchedule, PeriodicTask

TZ = settings.TIME_ZONE


class Command(BaseCommand):
    help = "Crea/actualiza las tareas periódicas de Sentinel XO en Celery Beat (DB scheduler)."

    def handle(self, *args, **options):
        created, updated = 0, 0

        def interval(every, period):
            sched, _ = IntervalSchedule.objects.get_or_create(every=every, period=period)
            return sched

        def crontab(minute="0", hour="*", day_of_week="*", day_of_month="*"):
            sched, _ = CrontabSchedule.objects.get_or_create(
                minute=minute, hour=hour, day_of_week=day_of_week,
                day_of_month=day_of_month, month_of_year="*", timezone=TZ,
            )
            return sched

        tasks = [
            dict(
                name="Conectividad de agentes (offline/recuperación)",
                task="core.check_offline_devices",
                schedule=interval(5, IntervalSchedule.MINUTES),
                description="Detecta equipos sin telemetría y crea/cierra incidentes de conectividad.",
            ),
            dict(
                name="Anomalías de inicio de sesión M365",
                task="core.check_signin_anomalies_all",
                schedule=interval(30, IntervalSchedule.MINUTES),
                description="Revisa inicios de sesión M365 recientes (países nuevos, viajes imposibles).",
            ),
            dict(
                name="Verificación SMTP horaria",
                task="emailmon.check_smtp_hourly",
                schedule=interval(1, IntervalSchedule.HOURS),
                description="Verifica el envío SMTP y crea incidente si falla.",
            ),
            dict(
                name="Monitoreo Email/M365 por cliente",
                task="emailmon.check_m365_all_clients",
                schedule=interval(1, IntervalSchedule.HOURS),
                description="Verifica autenticación Azure AD, Exchange Online y envío/recepción real.",
            ),
            dict(
                name="Sincronización de licencias M365",
                task="monitoring.sync_m365_all_clients",
                schedule=interval(4, IntervalSchedule.HOURS),
                description="Sincroniza licencias Microsoft 365 de todos los clientes configurados.",
            ),
            dict(
                name="Verificación de dominios (WHOIS)",
                task="monitoring.refresh_all_domains",
                schedule=crontab(minute="0", hour="6"),
                description="Actualiza el estado WHOIS/DNS de todos los dominios activos.",
            ),
            dict(
                name="Alertas de vencimiento de dominios",
                task="monitoring.check_expiry_alerts",
                schedule=crontab(minute="0", hour="7"),
                description="Envía alertas por email/Telegram para dominios próximos a vencer (90/30/7 días).",
            ),
            dict(
                name="Limpieza de logs de email",
                task="emailmon.cleanup_old_logs",
                schedule=crontab(minute="0", hour="4", day_of_month="1"),
                description="Elimina logs de email con más de 90 días de antigüedad.",
            ),
            dict(
                name="Reportes mensuales de mantenimiento",
                task="reports.generate_monthly_reports_all",
                schedule=crontab(minute="0", hour="5", day_of_month="1"),
                description="Genera y envía el reporte PDF mensual a todos los clientes activos.",
            ),
            dict(
                name="Respaldo semanal de la base de datos",
                task="core.backup_database",
                schedule=crontab(minute="0", hour="3", day_of_week="1"),
                description="Genera un dump comprimido de los datos críticos y lo envía por email.",
            ),
        ]

        for t in tasks:
            schedule = t.pop("schedule")
            defaults = {
                "task": t["task"],
                "description": t["description"],
                "enabled": True,
            }
            if isinstance(schedule, IntervalSchedule):
                defaults["interval"] = schedule
                defaults["crontab"] = None
            else:
                defaults["crontab"] = schedule
                defaults["interval"] = None

            obj, was_created = PeriodicTask.objects.update_or_create(
                name=t["name"], defaults=defaults,
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + creada: {t['name']} ({t['task']})"))
            else:
                updated += 1
                self.stdout.write(f"  = actualizada: {t['name']} ({t['task']})")

        self.stdout.write(self.style.SUCCESS(
            f"\nListo: {created} tarea(s) creada(s), {updated} actualizada(s)."
        ))
