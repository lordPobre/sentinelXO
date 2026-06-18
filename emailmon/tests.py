"""
Tests de la app emailmon de Sentinel XO.

Verifican el registro de emails (EmailLog) y de verificaciones SMTP (SmtpCheck):
estados, categorías y la relación opcional con cliente. No se prueba el envío
real vía Resend (eso requiere red y API key), solo el modelado del registro.

Se ejecutan con: python manage.py test emailmon
"""
from django.test import TestCase
from core.models import Client
from emailmon.models import EmailLog, SmtpCheck


def _client(**kw):
    n = Client.objects.count() + 1
    defaults = dict(
        company_name=f"Cliente {n}",
        rut=f"{40000000 + n}-{n % 10}",
        contact_email=f"mail{n}@example.com",
    )
    defaults.update(kw)
    return Client.objects.create(**defaults)


class EmailLogTests(TestCase):

    def test_crear_log_enviado(self):
        log = EmailLog.objects.create(
            recipient="dest@example.com", subject="Reporte mensual",
            category="report", status="sent",
        )
        self.assertEqual(log.status, "sent")
        self.assertEqual(EmailLog.objects.count(), 1)

    def test_log_con_error(self):
        log = EmailLog.objects.create(
            recipient="dest@example.com", subject="Alerta",
            category="alert", status="failed", error_msg="timeout",
        )
        self.assertEqual(log.status, "failed")
        self.assertIn("timeout", log.error_msg)

    def test_cliente_eliminado_conserva_log(self):
        client = _client()
        log = EmailLog.objects.create(
            recipient="x@example.com", subject="Test", client=client,
        )
        client.delete()
        log.refresh_from_db()
        self.assertIsNone(log.client_id)
        self.assertTrue(EmailLog.objects.filter(pk=log.pk).exists())

    def test_ordenamiento_mas_reciente_primero(self):
        EmailLog.objects.create(recipient="a@example.com", subject="Primero")
        EmailLog.objects.create(recipient="b@example.com", subject="Segundo")
        subjects = list(EmailLog.objects.values_list("subject", flat=True))
        self.assertEqual(subjects[0], "Segundo")


class SmtpCheckTests(TestCase):

    def test_crear_check_ok(self):
        check = SmtpCheck.objects.create(
            status="ok", smtp_host="smtp.office365.com", smtp_port=587,
            response_ms=120,
        )
        self.assertEqual(check.status, "ok")
        self.assertEqual(check.response_ms, 120)

    def test_check_con_error(self):
        check = SmtpCheck.objects.create(
            status="error", smtp_host="smtp.office365.com", smtp_port=587,
            error_msg="conexión rechazada",
        )
        self.assertEqual(check.status, "error")

    def test_latest_devuelve_el_mas_reciente(self):
        SmtpCheck.objects.create(status="error", smtp_host="h", smtp_port=587)
        ultimo = SmtpCheck.objects.create(status="ok", smtp_host="h", smtp_port=587)
        self.assertEqual(SmtpCheck.objects.latest().pk, ultimo.pk)
