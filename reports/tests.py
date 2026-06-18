"""
Tests de la app reports de Sentinel XO.

Verifican que la generación de PDF produce un documento válido y no se rompe
ante cambios de código. Son tests de humo (smoke tests): no validan el contenido
exacto del PDF, pero sí que se genera sin excepciones y con la firma correcta.

Se ejecutan con: python manage.py test reports
"""
from django.test import TestCase
from core.models import Client, HardwareDevice
from reports.security_report import build_security_report_pdf
from reports.system_overview import build_system_overview_pdf


def _client(**kw):
    n = Client.objects.count() + 1
    defaults = dict(
        company_name=f"Cliente {n}",
        rut=f"{20000000 + n}-{n % 10}",
        contact_email=f"reporte{n}@example.com",
    )
    defaults.update(kw)
    return Client.objects.create(**defaults)


class SystemOverviewPdfTests(TestCase):
    """PDF de producto (funcionamiento y arquitectura)."""

    def test_genera_pdf_valido(self):
        
        pdf = build_system_overview_pdf()
        self.assertIsInstance(pdf, bytes)
        self.assertGreater(len(pdf), 1000)
        self.assertTrue(pdf.startswith(b"%PDF-"))


class SecurityReportPdfTests(TestCase):
    """PDF de postura de seguridad por cliente."""

    def test_genera_pdf_sin_datos(self):
        client = _client()
        pdf = build_security_report_pdf(client)
        self.assertIsInstance(pdf, bytes)
        self.assertGreater(len(pdf), 1000)
        self.assertTrue(pdf.startswith(b"%PDF-"))

    def test_genera_pdf_con_dispositivo(self):
        client = _client()
        HardwareDevice.objects.create(client=client, hostname="PC-REPORTE")
        pdf = build_security_report_pdf(client)
        self.assertTrue(pdf.startswith(b"%PDF-"))
