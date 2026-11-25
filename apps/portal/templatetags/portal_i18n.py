"""Template filters for bilingual urgency and status badges."""

from __future__ import annotations

from django import template

from apps.portal.i18n import get_status_label, get_urgency_label

register = template.Library()


@register.filter(name="urgency_label")
def urgency_label(tier: str, lang: str = "en") -> str:
    return get_urgency_label(str(tier or ""), str(lang or "en"))


@register.filter(name="status_label")
def status_label(status_code: str, lang: str = "en") -> str:
    return get_status_label(str(status_code or ""), str(lang or "en"))
