"""End-to-End Local Portal Tests: Real Media/Voice Upload, Field Resolution, Two-Key & Crisis Toggle."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from apps.complaints.models import AuditLog, Complaint


@pytest.mark.django_db
@override_settings(
    USE_REMOTE_AI_SERVICE=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
def test_local_end_to_end_citizen_field_twokey_and_crisis_flow(client, ndc_org_fixture):
    env = ndc_org_fixture

    # 1. Citizen submits multipart complaint with real photo + voice blob (no MinIO/AI container)
    photo = SimpleUploadedFile("pothole.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")
    voice = SimpleUploadedFile("note.webm", b"fake-audio-bytes", content_type="audio/webm")
    resp_sub = client.post(
        reverse("portal:htmx-submit"),
        {
            "raw_text_en": "Burst WASA pipe and broken DNCC road in Gulshan-2.",
            "lat": "23.7925",
            "lon": "90.4143",
            "photo_file": photo,
            "voice_audio_file": voice,
        },
    )
    assert resp_sub.status_code == 200
    complaint = Complaint.objects.order_by("-created_at").first()
    assert complaint is not None
    assert "/media/voice/" in complaint.voice_audio_url

    # 2. Field Worker submits geo-tagged After photo within 100m -> PENDING_CITIZEN_VERIFY
    after_photo = SimpleUploadedFile("after.jpg", b"fixed-jpeg-bytes", content_type="image/jpeg")
    resp_fw = client.post(
        reverse("portal:htmx-field-submit"),
        {
            "complaint_id": str(complaint.complaint_id),
            "submitted_by_seat": env["fw"].doptor_seat_id,
            "supervisor_signoff_seat": env["sup"].doptor_seat_id,
            "work_summary": "Replaced broken pipe and resurfaced Gulshan-2 carriageway.",
            "after_lat": "23.7926",
            "after_lon": "90.4144",
            "after_photo_file": after_photo,
        },
    )
    assert resp_fw.status_code == 200
    complaint.refresh_from_db()
    assert complaint.status == Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY

    # 3. Citizen accepts via Two-Key Verification -> CLOSED
    resp_vk = client.post(
        reverse("portal:htmx-two-key-verdict", args=[complaint.complaint_id]),
        {"verdict": "ACCEPTED", "feedback": "Verified fixed on site."},
    )
    assert resp_vk.status_code == 200
    complaint.refresh_from_db()
    assert complaint.status == Complaint.ComplaintStatus.CLOSED

    # 4. Command Center Crisis Mode Toggle works with HTTP 200
    resp_crisis = client.post(reverse("portal:htmx-toggle-crisis"))
    assert resp_crisis.status_code == 200
    assert AuditLog.verify_chain()[0] is True
