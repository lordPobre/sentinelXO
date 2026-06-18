"""
Tests de la app dashboard de Sentinel XO.

Se centran en el control de acceso, que es lo más sensible:
  - Las vistas requieren autenticación (redirigen al login si no hay sesión).
  - Un cliente solo puede ver su propio portal, no el de otro cliente.
  - Un admin (staff) puede ver cualquier portal.

Se ejecutan con: python manage.py test dashboard
"""
from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Client

User = get_user_model()


def _client(**kw):
    n = Client.objects.count() + 1
    defaults = dict(
        company_name=f"Cliente {n}",
        rut=f"{50000000 + n}-{n % 10}",
        contact_email=f"dash{n}@example.com",
    )
    defaults.update(kw)
    return Client.objects.create(**defaults)


@override_settings(SECURE_SSL_REDIRECT=False)
class AccesoNoAutenticadoTests(TestCase):
    """Las vistas protegidas redirigen al login."""

    def test_home_requiere_login(self):
        resp = self.client.get(reverse("dashboard:home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/auth/login", resp.url)

    def test_admin_overview_requiere_login(self):
        resp = self.client.get(reverse("dashboard:admin-overview"))
        self.assertEqual(resp.status_code, 302)


@override_settings(SECURE_SSL_REDIRECT=False)
class PortalAislamientoTests(TestCase):
    """Un cliente no puede acceder al portal de otro cliente."""

    def setUp(self):
        self.client_a = _client()
        self.client_b = _client()
        self.user_a = User.objects.create_user(username="user_a", password="pass12345")
        self.client_a.portal_users.add(self.user_a)

    def test_cliente_ve_su_propio_portal(self):
        self.client.login(username="user_a", password="pass12345")
        resp = self.client.get(reverse("dashboard:client-portal", args=[self.client_a.id]))
        self.assertEqual(resp.status_code, 200)

    def test_cliente_no_ve_portal_ajeno(self):
        self.client.login(username="user_a", password="pass12345")
        resp = self.client.get(reverse("dashboard:client-portal", args=[self.client_b.id]))
        self.assertEqual(resp.status_code, 404)

    def test_admin_ve_cualquier_portal(self):
        admin = User.objects.create_user(
            username="admin", password="pass12345", is_staff=True,
        )
        self.client.login(username="admin", password="pass12345")
        resp = self.client.get(reverse("dashboard:client-portal", args=[self.client_b.id]))
        self.assertEqual(resp.status_code, 200)


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminOverviewAccesoTests(TestCase):
    """La vista de resumen global es accesible para staff autenticado."""

    def test_staff_accede_overview(self):
        admin = User.objects.create_user(
            username="admin2", password="pass12345", is_staff=True,
        )
        self.client.login(username="admin2", password="pass12345")
        resp = self.client.get(reverse("dashboard:admin-overview"))
        self.assertEqual(resp.status_code, 200)
