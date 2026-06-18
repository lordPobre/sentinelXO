"""
Tests de la app monitoring de Sentinel XO.

Los modelos de dominio viven en core, pero la lógica de estado por vencimiento
(refresh_status / refresh_ssl_status) es el corazón del monitoreo de dominios,
así que se prueba aquí. Son tests de lógica pura, sin red ni WHOIS real.

Se ejecutan con: python manage.py test monitoring
"""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from core.models import Client, Domain


def _client(**kw):
    n = Client.objects.count() + 1
    defaults = dict(
        company_name=f"Cliente {n}",
        rut=f"{30000000 + n}-{n % 10}",
        contact_email=f"dom{n}@example.com",
    )
    defaults.update(kw)
    return Client.objects.create(**defaults)


def _domain(client, **kw):
    defaults = dict(fqdn="ejemplo.cl")
    defaults.update(kw)
    return Domain.objects.create(client=client, **defaults)


class DomainExpiryStatusTests(TestCase):
    """Lógica de estado de vencimiento de dominio (umbrales 90/30/0 días)."""

    def setUp(self):
        self.client_obj = _client()
        self.today = timezone.now().date()

    def _status_for(self, days_until):
        d = _domain(self.client_obj, expiry_date=self.today + timedelta(days=days_until))
        d.refresh_status()
        return d.status

    def test_vigente_es_ok(self):
        self.assertEqual(self._status_for(120), "ok")

    def test_menos_de_90_dias_es_warning(self):
        self.assertEqual(self._status_for(60), "warning")

    def test_menos_de_30_dias_es_critical(self):
        self.assertEqual(self._status_for(15), "critical")

    def test_vencido_es_expired(self):
        self.assertEqual(self._status_for(-5), "expired")

    def test_sin_fecha_es_unknown(self):
        d = _domain(self.client_obj, expiry_date=None)
        d.refresh_status()
        self.assertEqual(d.status, "unknown")

    def test_days_until_expiry(self):
        d = _domain(self.client_obj, expiry_date=self.today + timedelta(days=45))
        self.assertEqual(d.days_until_expiry, 45)

    def test_days_until_expiry_sin_fecha(self):
        d = _domain(self.client_obj, expiry_date=None)
        self.assertIsNone(d.days_until_expiry)


class DomainSslStatusTests(TestCase):
    """Lógica de estado del certificado SSL (umbrales 30/15/0 días)."""

    def setUp(self):
        self.client_obj = _client()
        self.today = timezone.now().date()

    def _ssl_status_for(self, days_until, error=""):
        d = _domain(
            self.client_obj,
            ssl_expiry_date=self.today + timedelta(days=days_until),
            ssl_error=error,
        )
        d.refresh_ssl_status()
        return d.ssl_status

    def test_ssl_vigente_es_ok(self):
        self.assertEqual(self._ssl_status_for(60), "ok")

    def test_ssl_menos_de_30_es_warning(self):
        self.assertEqual(self._ssl_status_for(20), "warning")

    def test_ssl_menos_de_15_es_critical(self):
        self.assertEqual(self._ssl_status_for(10), "critical")

    def test_ssl_vencido_es_expired(self):
        self.assertEqual(self._ssl_status_for(-1), "expired")

    def test_ssl_con_error_es_unknown(self):
        self.assertEqual(self._ssl_status_for(60, error="handshake failed"), "unknown")


class DomainUniquenessTests(TestCase):
    """Restricción de unicidad cliente + fqdn."""

    def test_mismo_dominio_distinto_cliente_permitido(self):
        c1 = _client()
        c2 = _client()
        _domain(c1, fqdn="compartido.cl")
        _domain(c2, fqdn="compartido.cl")
        self.assertEqual(Domain.objects.filter(fqdn="compartido.cl").count(), 2)
