"""Automated tests for Part 9: Idempotent Demo Scenario Seeder & 1-Click Role Switcher."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.accounts.demo_roles import DEMO_PASSWORD, DEMO_ROLES
from apps.accounts.models import User, WhistleblowerVaultRecord
from apps.ai_triage.models import MasterIncidentSubscription, SubTicketDependency
from apps.complaints.models import AuditLog, Complaint
from apps.disaster.models import CrisisZone, EmergencyCommandDispatch
from apps.workflow.models import ArbitrationCase, CapitalMilestone


@pytest.mark.django_db
@override_settings(VAULT_MODE="local_dev", KAFKA_PROVIDER_MODE="mock", DEMO_MODE=True)
def test_seed_demo_scenarios_is_idempotent_and_populates_all_statutory_cases():
    # Run twice to guarantee full idempotency
    call_command("seed_demo_scenarios", stdout=StringIO())
    first_count = Complaint.objects.count()
    call_command("seed_demo_scenarios", stdout=StringIO())
    second_count = Complaint.objects.count()

    assert first_count >= 25
    assert second_count == first_count

    # Verify all 8 demo accounts exist and accept Demo@2026
    for role in DEMO_ROLES:
        user = User.objects.get(username=role["username"])
        assert user.check_password(DEMO_PASSWORD)

    # Verify every seeded statutory scenario
    assert SubTicketDependency.objects.count() >= 2
    assert MasterIncidentSubscription.objects.count() >= 12
    assert Complaint.objects.filter(status=Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY).count() >= 2
    assert Complaint.objects.filter(status=Complaint.ComplaintStatus.ARBITRATION_LOCKED, transfer_count=2).exists()
    assert ArbitrationCase.objects.exists()
    assert Complaint.objects.filter(status=Complaint.ComplaintStatus.ON_HOLD_PROCUREMENT).exists()
    assert CapitalMilestone.objects.count() >= 4
    assert Complaint.objects.filter(status=Complaint.ComplaintStatus.CONTESTED_BY_OFFICER).exists()
    assert Complaint.objects.filter(status=Complaint.ComplaintStatus.UNFOUNDED_CLEARED).exists()
    assert WhistleblowerVaultRecord.objects.exists()
    assert CrisisZone.objects.filter(is_active=True).exists()
    assert EmergencyCommandDispatch.objects.count() >= 2
    assert Complaint.objects.filter(status=Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED).count() >= 2

    # Verify intact SHA-256 hash chain across all seeded AuditLog entries
    is_valid, checked, broken = AuditLog.verify_chain()
    assert is_valid is True
    assert checked >= 20
    assert broken is None


@pytest.mark.django_db
@override_settings(DEBUG=True, DEMO_MODE=True)
def test_demo_role_switcher_logs_in_and_redirects_to_role_workspace(client):
    call_command("seed_demo_scenarios", stdout=StringIO())
    switch_url = reverse("accounts:demo-role-switch")

    for role in DEMO_ROLES:
        resp = client.post(switch_url, {"username": role["username"]})
        assert resp.status_code == 302
        assert resp["Location"] == role["redirect_url"]


@pytest.mark.django_db
@override_settings(DEBUG=False, DEMO_MODE=False)
def test_demo_role_switcher_blocked_when_demo_mode_disabled(client):
    call_command("seed_demo_scenarios", stdout=StringIO())
    resp = client.post(reverse("accounts:demo-role-switch"), {"username": "command_admin"})
    assert resp.status_code == 403
