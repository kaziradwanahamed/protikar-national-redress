"""
End-to-End Integration Test Suite verifying all statutory safeguards for NDC production launch:
  1. Two-Key Closure Rule (Field Worker close block + 100m PostGIS gate + Citizen rejection escalation)
  2. Transfer Anti-Gaming (transfer_count <= 2, 15% SLA window, ARBITRATION_LOCKED)
  3. Zero-Black-Hole Seat Fallback (Primary -> Additional Charge -> Immediate Supervisor + HR Alert)
  4. SLA Escalation (80% warning, 100% APA breach, DDCC) & ON_HOLD_PROCUREMENT e-GP SLA pause
  5. Disaster Surge (5x Circuit Breaker + Kafka + H3 Res-8 Redis) & AuditLog SHA-256 Tamper Detection
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from apps.complaints.models import (
    AuditLog,
    AuditLogImmutabilityError,
    Complaint,
    ResolutionReport,
)
from apps.disaster.models import EmergencyCommandDispatch
from apps.disaster.services.circuit_breaker import DisasterCircuitBreakerService
from apps.disaster.services.h3_surge_pipeline import H3SurgeIngestionService
from apps.organogram.models import DoptorVacancyAlert, RoleLevel
from apps.organogram.services.seat_router import ZeroBlackHoleSeatRouter
from apps.workflow.models import (
    ArbitrationCase,
    CapitalMilestone,
    DDCCAgendaItem,
    EscalationEvent,
)
from apps.workflow.services.escalation_daemon import SLAEscalationDaemon
from apps.workflow.services.sla_service import TieredSLAService
from apps.workflow.services.state_machine import (
    GrievanceWorkflowEngine,
    WorkflowPermissionError,
    WorkflowTransitionError,
)


@pytest.mark.django_db
def test_e2e_two_key_closure_rule_and_citizen_rejection_escalation(ndc_org_fixture):
    env = ndc_org_fixture
    complaint = Complaint.objects.create(
        citizen_uct_hash=env["profile"].pseudonymous_public_hash,
        raw_text_en="Broken culvert on Gulshan Road 45.",
        urgency_tier=Complaint.UrgencyTier.P2,
        geo_point=env["point"],
        admin_geo_code="30262619",
    )
    TieredSLAService.route_complaint(complaint=complaint, target_seat_id=env["gro"].doptor_seat_id)
    TieredSLAService.assign_field_worker(
        complaint=complaint,
        supervisor_seat_id=env["sup"].doptor_seat_id,
        field_worker_seat_id=env["fw"].doptor_seat_id,
        actor_id="E2E-EMP-SUP",
    )

    # 1. Field Worker must NEVER directly close a complaint
    with pytest.raises(WorkflowPermissionError):
        GrievanceWorkflowEngine.assert_not_direct_field_close(
            RoleLevel.FIELD_WORKER, Complaint.ComplaintStatus.CLOSED
        )

    # 2. Resolution with photo within 100m + supervisor sign-off moves to PENDING_CITIZEN_VERIFY
    report = GrievanceWorkflowEngine.submit_resolution_for_verification(
        complaint=complaint,
        submitted_by_seat=env["fw"].doptor_seat_id,
        supervisor_signoff_seat=env["sup"].doptor_seat_id,
        work_summary="Replaced broken concrete slab and restored road level.",
        after_photo_urls=["https://minio.local/after-1.jpg"],
        after_lon=90.4144,
        after_lat=23.7926,
        actor_id="E2E-EMP-SUP",
    )
    assert report.gps_verified_dist_m <= 100.0
    complaint.refresh_from_db()
    assert complaint.status == Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY

    # 3. Citizen REJECT auto-reopens & escalates 1 tier up
    GrievanceWorkflowEngine.record_citizen_verdict(
        complaint=complaint,
        verdict=ResolutionReport.CitizenVerdict.REJECTED,
        citizen_actor_id=str(env["citizen"].id),
        feedback="Slab is still cracked and flooding persists.",
        evidence_urls=["https://minio.local/reject-evidence.jpg"],
    )
    complaint.refresh_from_db()
    assert complaint.status == Complaint.ComplaintStatus.IN_PROGRESS
    assert complaint.escalation_level == 1
    assert EscalationEvent.objects.filter(
        complaint=complaint, event_type=EscalationEvent.EventType.CITIZEN_REJECTION
    ).exists()


@pytest.mark.django_db
def test_e2e_transfer_anti_gaming_15pct_window_and_arbitration_lock(ndc_org_fixture):
    env = ndc_org_fixture
    complaint = Complaint.objects.create(
        citizen_uct_hash=env["profile"].pseudonymous_public_hash,
        raw_text_en="Drainage and water pipe overlap dispute.",
        urgency_tier=Complaint.UrgencyTier.P2,
        geo_point=env["point"],
        admin_geo_code="30262619",
    )
    tracker, _ = TieredSLAService.route_complaint(
        complaint=complaint, target_seat_id=env["gro"].doptor_seat_id
    )

    # Reject transfer past 15% of SLA window
    late_time = tracker.sla_started_at + timedelta(seconds=int(tracker.sla_total_seconds * 0.25))
    with pytest.raises(WorkflowTransitionError):
        GrievanceWorkflowEngine.request_transfer(
            complaint=complaint,
            from_seat_id=env["gro"].doptor_seat_id,
            target_seat_id=env["wasa_gro"].doptor_seat_id,
            reason="Late transfer attempt after 25% SLA.",
            actor_id="E2E-EMP-GRO",
            now=late_time,
        )

    # 1st transfer within 15% SLA succeeds; 2nd refusal locks into ARBITRATION_LOCKED
    res1 = GrievanceWorkflowEngine.request_transfer(
        complaint=complaint,
        from_seat_id=env["gro"].doptor_seat_id,
        target_seat_id=env["wasa_gro"].doptor_seat_id,
        reason="Belongs to WASA MODS.",
        actor_id="E2E-EMP-GRO",
    )
    assert res1["transfer_count"] == 1

    res2 = GrievanceWorkflowEngine.request_transfer(
        complaint=complaint,
        from_seat_id=env["wasa_gro"].doptor_seat_id,
        target_seat_id=env["gro"].doptor_seat_id,
        reason="Belongs to DNCC drainage.",
        actor_id="E2E-EMP-WASA",
    )
    assert res2["status"] == Complaint.ComplaintStatus.ARBITRATION_LOCKED
    complaint.refresh_from_db()
    assert complaint.transfer_count == 2
    assert complaint.is_arbitration_locked is True
    assert ArbitrationCase.objects.filter(complaint=complaint).exists()

    # 3rd transfer must be hard-blocked
    with pytest.raises(WorkflowTransitionError):
        GrievanceWorkflowEngine.request_transfer(
            complaint=complaint,
            from_seat_id=env["gro"].doptor_seat_id,
            target_seat_id=env["wasa_gro"].doptor_seat_id,
            reason="Forbidden 3rd transfer.",
            actor_id="E2E-EMP-GRO",
        )


@pytest.mark.django_db
def test_e2e_zero_black_hole_seat_fallback_chain(ndc_org_fixture):
    env = ndc_org_fixture
    router = ZeroBlackHoleSeatRouter()

    # Tier 1: Primary occupied
    r1 = router.resolve_seat(target_seat_id=env["gro"].doptor_seat_id, fire_hr_alert=False)
    assert r1.resolved_seat.doptor_seat_id == env["gro"].doptor_seat_id

    # Tier 2: Primary vacant -> Additional Charge Seat
    env["gro"].is_vacant = True
    env["gro"].incumbent_officer_id = ""
    env["gro"].save()
    r2 = router.resolve_seat(target_seat_id=env["gro"].doptor_seat_id, fire_hr_alert=False)
    assert r2.resolved_seat.doptor_seat_id == env["addl_gro"].doptor_seat_id

    # Tier 3: Additional Charge also unavailable -> Immediate Supervisor + Doptor HR Vacancy Alert
    env["gro"].additional_charge_seat = None
    env["gro"].save()
    r3 = router.resolve_seat(target_seat_id=env["gro"].doptor_seat_id, fire_hr_alert=False)
    assert r3.resolved_seat.doptor_seat_id == env["appellate"].doptor_seat_id
    assert r3.vacancy_alert is not None
    assert DoptorVacancyAlert.objects.count() == 1


@pytest.mark.django_db
def test_e2e_sla_escalation_and_egp_procurement_hold(ndc_org_fixture):
    env = ndc_org_fixture
    complaint = Complaint.objects.create(
        citizen_uct_hash=env["profile"].pseudonymous_public_hash,
        raw_text_en="Major arterial road reconstruction needed.",
        urgency_tier=Complaint.UrgencyTier.P2,
        geo_point=env["point"],
        admin_geo_code="30262619",
    )
    tracker, _ = TieredSLAService.route_complaint(
        complaint=complaint, target_seat_id=env["gro"].doptor_seat_id
    )

    # 80% elapsed -> Yellow Warning
    t85 = tracker.sla_started_at + timedelta(seconds=int(tracker.sla_total_seconds * 0.85))
    sweep85 = SLAEscalationDaemon.run_sweep(now=t85)
    assert sweep85["yellow_warnings_80pct"] == 1

    # 100% breach at Tier 3 -> APA impact + Monthly DDCC Agenda Item
    complaint.escalation_level = 2
    complaint.save(update_fields=["escalation_level"])
    t110 = tracker.sla_started_at + timedelta(seconds=int(tracker.sla_total_seconds * 1.10))
    sweep110 = SLAEscalationDaemon.run_sweep(now=t110)
    assert sweep110["sla_breaches_escalated"] == 1
    assert DDCCAgendaItem.objects.filter(complaint=complaint).exists()

    # ON_HOLD_PROCUREMENT pauses SLA via verified e-GP Tender ID
    complaint.status = Complaint.ComplaintStatus.IN_PROGRESS
    complaint.save(update_fields=["status"])
    milestones = GrievanceWorkflowEngine.place_on_hold_procurement(
        complaint=complaint,
        seat_id=env["gro"].doptor_seat_id,
        actor_id="E2E-EMP-GRO",
        reference_type=CapitalMilestone.ReferenceType.EGP_TENDER,
        reference_id="EGP-2026-771204",
    )
    assert len(milestones) == 4
    tracker.refresh_from_db()
    assert tracker.is_sla_paused is True


@pytest.mark.django_db
@override_settings(KAFKA_PROVIDER_MODE="mock", DISASTER_SURGE_MULTIPLIER=5.0)
def test_e2e_disaster_h3_surge_and_sha256_audit_tamper_detection(ndc_org_fixture):
    env = ndc_org_fixture

    # 1. Disaster 5x surge + H3 Res-8 Redis counter + P1 Fast-Lane
    for _ in range(6):
        cb = DisasterCircuitBreakerService.record_polygon_hit(
            zone_code=env["zone"].zone_code, baseline_per_hour=1.0
        )
    assert cb["circuit_breaker_tripped"] is True

    surge = H3SurgeIngestionService.ingest_surge_report(
        lat=23.7925,
        lon=90.4143,
        message="Citizens trapped on roof with live wire in water!",
        citizen_phone="+8801711223344",
    )
    assert surge.fastlane_triggered is True
    assert EmergencyCommandDispatch.objects.count() == 1

    # 2. AuditLog immutability & SHA-256 tamper detection
    entry = AuditLog.objects.create(
        actor_id="E2E-AUDITOR",
        actor_role="SYSTEM",
        action="E2E_INTEGRITY_CHECK",
        entity_type="System",
        entity_id="NDC-01",
        payload={"ok": True},
    )
    assert AuditLog.verify_chain()[0] is True

    with pytest.raises(AuditLogImmutabilityError):
        entry.action = "TAMPERED_ACTION"
        entry.save()

    with pytest.raises(AuditLogImmutabilityError):
        entry.delete()

    # Simulate rogue direct SQL tampering -> verify_chain() MUST detect the exact broken log_id
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE complaints_audit_log SET action = %s WHERE log_id = %s",
            ["ROGUE_SQL_TAMPER", str(entry.log_id)],
        )
    is_valid, _checked, broken_id = AuditLog.verify_chain()
    assert is_valid is False
    assert broken_id == str(entry.log_id)
