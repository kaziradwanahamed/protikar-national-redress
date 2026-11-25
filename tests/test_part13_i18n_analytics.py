"""Part 13 tests: Bilingual Bangla/English switcher, Public Transparency Analytics, SHA-256 Verifier & Route Smoke Checks."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from apps.complaints.models import AuditLog, Complaint, ResolutionReport
from apps.portal.i18n import get_status_label, get_urgency_label


@pytest.mark.django_db
def test_bilingual_language_switcher_persists_in_session():
    client = Client()
    resp = client.post(
        reverse("portal:set-language"),
        {"lang": "bn", "next": "/analytics/"},
        follow=True,
    )
    assert resp.status_code == 200
    assert client.session["portal_lang"] == "bn"
    body = resp.content.decode("utf-8")
    assert "জাতীয় অভিযোগ নিষ্পত্তি স্বচ্ছতা ও এসএলএ বিশ্লেষণ" in body
    assert get_urgency_label("P1", "bn") == "P1 জরুরি"
    assert get_urgency_label("P2", "bn") == "P2 অতি জরুরি"
    assert get_urgency_label("P3", "bn") == "P3 সাধারণ"
    assert get_urgency_label("P4", "bn") == "P4 অবকাঠামো"
    assert get_status_label("PENDING_CITIZEN_VERIFY", "bn") == "নাগরিক যাচাইয়ের অপেক্ষায়"

    resp_en = client.post(
        reverse("portal:set-language"),
        {"lang": "en", "next": "/analytics/"},
        follow=True,
    )
    assert resp_en.status_code == 200
    assert client.session["portal_lang"] == "en"
    assert "National Redress Transparency & SLA Analytics" in resp_en.content.decode("utf-8")


@pytest.mark.django_db
def test_public_analytics_and_sha256_audit_chain_verifier():
    c = Complaint.objects.create(
        citizen_uct_hash="a" * 64,
        raw_text_en="Burst WASA water pipe at Mirpur-10",
        ai_category_code="WASA_WATER_LEAK",
        urgency_tier=Complaint.UrgencyTier.P1,
        status=Complaint.ComplaintStatus.CLOSED,
    )
    ResolutionReport.objects.create(
        complaint=c,
        submitted_by_seat="SEAT-WASA-MODS4-FIELD",
        work_summary="Pipe joint replaced and pressure verified.",
        citizen_verdict=ResolutionReport.CitizenVerdict.ACCEPTED,
    )
    AuditLog.objects.create(
        complaint=c,
        actor_type="SYSTEM",
        actor_id="test_runner",
        action="TWO_KEY_ACCEPTED",
        payload={"tracking_code": c.tracking_code},
    )

    client = Client()
    resp = client.get(reverse("portal:analytics"))
    assert resp.status_code == 200
    html = resp.content.decode("utf-8")
    assert "WASA" in html
    assert "DPDC" in html
    assert "DESCO" in html
    assert "BRTA" in html
    assert "deptLeaderboardChart" in html

    verify_resp = client.post(reverse("portal:htmx-verify-audit-chain"))
    assert verify_resp.status_code == 200
    assert "SHA-256 OK" in verify_resp.content.decode("utf-8")

    json_resp = client.post(
        reverse("portal:htmx-verify-audit-chain"),
        HTTP_ACCEPT="application/json",
    )
    assert json_resp.status_code == 200
    payload = json_resp.json()
    assert payload["is_valid"] is True
    assert payload["checked_count"] >= 1


@pytest.mark.django_db
def test_all_national_portal_routes_return_http_200():
    client = Client()
    for url in ("/", "/udc/", "/officer/", "/officer/field/", "/command/", "/analytics/", "/admin/login/"):
        resp = client.get(url)
        assert resp.status_code == 200, f"Expected HTTP 200 for {url}, got {resp.status_code}"
