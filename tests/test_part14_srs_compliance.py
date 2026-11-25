"""Part 14 tests: FR01 OTP+NID/BRN, FR07 Progress Updates, FR09 Notifications, FR020 ESB Sync & NFR06 Backup."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from apps.complaints.models import CitizenNotification, Complaint, ComplaintProgressUpdate
from apps.esb.models import AgencyEndpoint, ESBDeliveryLog


@pytest.mark.django_db
def test_fr01_citizen_otp_and_nid_verification_login():
    client = Client()
    req_resp = client.post(
        reverse("portal:htmx-otp-request"),
        {"phone_number": "+8801711000099"},
    )
    assert req_resp.status_code == 200
    data = req_resp.json()
    assert data["ok"] is True

    ver_resp = client.post(
        reverse("portal:htmx-otp-verify"),
        {
            "challenge_id": data["challenge_id"],
            "phone_number": "+8801711000099",
            "otp_code": data["dev_otp"],
            "id_type": "NID",
            "id_number": "1994261234567",
        },
    )
    assert ver_resp.status_code == 200
    assert "Verified via" in ver_resp.content.decode("utf-8")


@pytest.mark.django_db
def test_fr07_progress_update_and_fr09_notifications():
    c = Complaint.objects.create(
        citizen_uct_hash="b" * 64,
        raw_text_en="DPDC transformer sparking in Mirpur-10",
        status=Complaint.ComplaintStatus.IN_PROGRESS,
    )
    client = Client()
    resp = client.post(
        reverse("portal:htmx-officer-action", args=[c.complaint_id]),
        {"action": "progress_update", "progress_message": "Site inspection completed, transformer parts requisitioned."},
    )
    assert resp.status_code == 200
    assert ComplaintProgressUpdate.objects.filter(complaint=c).count() == 1
    assert CitizenNotification.objects.filter(complaint=c, channel="SMS").exists()

    track_resp = client.get(reverse("portal:htmx-track"), {"tracking_code": c.tracking_code})
    assert track_resp.status_code == 200
    assert "transformer parts requisitioned" in track_resp.content.decode("utf-8")


@pytest.mark.django_db
def test_fr020_esb_sync_and_nfr06_backup():
    ep = AgencyEndpoint.objects.create(
        agency_code="GRS",
        agency_name="Cabinet Division GRS (grs.gov.bd)",
        tier=AgencyEndpoint.IntegrationTier.TIER_1_REST_WEBHOOK,
    )
    client = Client()
    sync_resp = client.post(reverse("portal:htmx-esb-sync", args=[ep.agency_code]))
    assert sync_resp.status_code == 200
    assert "HTTP 200 Healthy" in sync_resp.content.decode("utf-8")
    assert ESBDeliveryLog.objects.filter(agency_code="GRS").exists()

    with tempfile.TemporaryDirectory() as tmpdir:
        call_command("backup_system", output_dir=tmpdir)
        json_files = list(Path(tmpdir).glob("protikar_backup_*.json"))
        assert len(json_files) == 1
