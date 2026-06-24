"""
Template tags para el Score de Seguridad.

Uso:
  {% load security_score_tags %}

  En el dashboard del cliente (cálculo en vivo + tendencia):
    {% security_score client as sc %}
    {% include "partials/security_score_card.html" %}

  En la lista de clientes (badge liviano, lee el último snapshot):
    {% client_score_badge client as b %}
    {% include "partials/security_score_badge.html" %}
"""
from django import template
from core.models import SecurityScoreSnapshot
from core.security_score import compute_security_score, get_score_delta, grade_color
import math

register = template.Library()

_GAUGE_C = round(2 * math.pi * 42, 1)  # circunferencia del anillo (r=42)


@register.simple_tag
def security_score(client):
    """Cálculo en vivo + delta de tendencia. Para el dashboard del cliente."""
    r = compute_security_score(client)
    r["delta"] = get_score_delta(client, r["score"])
    r["gauge_c"] = _GAUGE_C
    r["gauge_offset"] = round(_GAUGE_C * (1 - r["score"] / 100), 1)
    return r


@register.simple_tag
def client_score_badge(client):
    """
    Badge liviano para listados: usa el último snapshot guardado (barato).
    Si aún no hay snapshot, calcula en vivo una vez como respaldo.
    """
    snap = SecurityScoreSnapshot.objects.filter(client=client).first()
    if snap:
        return {"score": snap.score, "grade": snap.grade, "color": grade_color(snap.grade)}
    r = compute_security_score(client)
    return {"score": r["score"], "grade": r["grade"], "color": r["color"]}
