from datetime import timedelta

from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import CitizenProfile, User
from apps.accounts.services.oidc_providers import CitizenIdentityService, get_identity_provider
from apps.complaints.models import AuditLog, Complaint, ResolutionReport
from apps.organogram.models import DoptorOffice, DoptorSeat, RoleLevel
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


class WorkflowGovernanceEngineTests(TestCase):
    def setUp(self):
        self.office = DoptorOffice.objects.create(
            doptor_office_id="DOPTOR-WF-DNCC",
            office_code="DNCC-WF",
            name_en="DNCC Zone 3",
            office_layer=DoptorOffice.OfficeLayer.CITY_CORP,
            ministry_code="MIN-LGRD",
            district_code="26",
            upazila_code="26",
            bbs_geo_code="302626",
        )
        self.other_office = DoptorOffice.objects.create(
            doptor_office_id="DOPTOR-WF-DWASA",
            office_code="DWASA-WF",
            name_en="Dhaka WASA MODS 4",
            office_layer=DoptorOffice.OfficeLayer.UTILITY,
            ministry_code="MIN-LGRD",
            district_code="26",
            upazila_code="48",
            bbs_geo_code="302648",
        )
        self.appellate_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-WF-APP",
            office=self.office,
            designation_en="CEO DNCC",
            role_level=RoleLevel.APPELLATE,
            incumbent_officer_id="OFF-APP-1",
        )
        self.gro_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-WF-GRO",
            office=self.office,
            designation_en="GRO Zone 3",
            role_level=RoleLevel.GRO,
            parent_seat=self.appellate_seat,
            incumbent_officer_id="OFF-GRO-1",
        )
        self.sup_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-WF-SUP",
            office=self.office,
            designation_en="Assistant Engineer",
            role_level=RoleLevel.SUPERVISOR,
            parent_seat=self.gro_seat,
            incumbent_officer_id="OFF-SUP-1",
        )
        self.fw_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-WF-FW",
            office=self.office,
            designation_en="Sub-Assistant Engineer",
            role_level=RoleLevel.FIELD_WORKER,
            parent_seat=self.sup_seat,
            incumbent_officer_id="OFF-FW-1",
        )
        self.wasa_gro_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-WF-WASA-GRO",
            office=self.other_office,
            designation_en="WASA Executive Engineer",
            role_level=RoleLevel.GRO,
            incumbent_officer_id="OFF-WASA-1",
        )

        claims = get_identity_provider().exchange_code_for_claims("wf-citizen-code")
        self.citizen, self.profile = CitizenIdentityService.upsert_from_oidc_claims(claims)
        self.adjudicator = User.objects.create_user(
            username="appellate_adj",
            account_type=User.AccountType.OFFICER,
            doptor_seat_id=self.appellate_seat.doptor_seat_id,
            doptor_role_level=RoleLevel.APPELLATE,
        )

        self.complaint = Complaint.objects.create(
            citizen_uct_hash=self.profile.pseudonymous_public_hash,
            raw_text_en="Broken water main and road cave-in at Gulshan-2.",
            urgency_tier=Complaint.UrgencyTier.P2,
            geo_point=Point(90.4143, 23.7925, srid=4326),
            admin_geo_code="30262619",
        )

    def test_tiered_sla_and_70pct_field_worker_subdeadline(self):
        self.assertEqual(TieredSLAService.get_sla_duration(Complaint.UrgencyTier.P1), timedelta(hours=4))
        self.assertEqual(TieredSLAService.get_sla_duration(Complaint.UrgencyTier.P2), timedelta(hours=48))
        self.assertEqual(TieredSLAService.get_sla_duration(Complaint.UrgencyTier.P3, p3_days=12), timedelta(days=12))
        self.assertEqual(TieredSLAService.get_sla_duration(Complaint.UrgencyTier.P4), timedelta(days=30))

        tracker, _assign = TieredSLAService.route_complaint(
            complaint=self.complaint, target_seat_id=self.gro_seat.doptor_seat_id
        )
        fw_assign = TieredSLAService.assign_field_worker(
            complaint=self.complaint,
            supervisor_seat_id=self.sup_seat.doptor_seat_id,
            field_worker_seat_id=self.fw_seat.doptor_seat_id,
            actor_id="OFF-SUP-1",
        )
        expected_70 = tracker.sla_started_at + timedelta(seconds=int(48 * 3600 * 0.70))
        self.assertEqual(fw_assign.due_at, expected_70)
        self.assertEqual(self.complaint.status, Complaint.ComplaintStatus.IN_PROGRESS)

    def test_two_key_gate_blocks_far_gps_and_allows_near_gps_then_citizen_accept(self):
        TieredSLAService.route_complaint(
            complaint=self.complaint, target_seat_id=self.gro_seat.doptor_seat_id
        )
        TieredSLAService.assign_field_worker(
            complaint=self.complaint,
            supervisor_seat_id=self.sup_seat.doptor_seat_id,
            field_worker_seat_id=self.fw_seat.doptor_seat_id,
            actor_id="OFF-SUP-1",
        )

        # Direct close by field worker must be blocked
        with self.assertRaises(WorkflowPermissionError):
            GrievanceWorkflowEngine.assert_not_direct_field_close(
                RoleLevel.FIELD_WORKER, Complaint.ComplaintStatus.CLOSED
            )

        # Photo > 100m away must fail
        with self.assertRaises(WorkflowTransitionError):
            GrievanceWorkflowEngine.submit_resolution_for_verification(
                complaint=self.complaint,
                submitted_by_seat=self.fw_seat.doptor_seat_id,
                supervisor_signoff_seat=self.sup_seat.doptor_seat_id,
                work_summary="Repaired broken pipe and resurfaced road.",
                after_photo_urls=["https://minio.local/after-far.jpg"],
                after_lon=90.4200,
                after_lat=23.7980,
                actor_id="OFF-SUP-1",
            )

        # Photo within ~25m succeeds -> PENDING_CITIZEN_VERIFY
        report = GrievanceWorkflowEngine.submit_resolution_for_verification(
            complaint=self.complaint,
            submitted_by_seat=self.fw_seat.doptor_seat_id,
            supervisor_signoff_seat=self.sup_seat.doptor_seat_id,
            work_summary="Repaired broken pipe and resurfaced road with asphalt.",
            after_photo_urls=["https://minio.local/after-near.jpg"],
            after_lon=90.4144,
            after_lat=23.7926,
            actor_id="OFF-SUP-1",
        )
        self.assertLessEqual(report.gps_verified_dist_m, 100.0)
        self.assertEqual(self.complaint.status, Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY)

        # Citizen ACCEPT -> CLOSED
        GrievanceWorkflowEngine.record_citizen_verdict(
            complaint=self.complaint,
            verdict=ResolutionReport.CitizenVerdict.ACCEPTED,
            citizen_actor_id=str(self.citizen.id),
            feedback="Verified on site, road is fixed.",
        )
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Complaint.ComplaintStatus.CLOSED)
        self.assertTrue(AuditLog.verify_chain()[0])

    def test_transfer_cap_arbitration_lock_and_p1_accept_first(self):
        # P1 ticket cannot be transferred before acceptance
        p1 = Complaint.objects.create(
            citizen_uct_hash=self.profile.pseudonymous_public_hash,
            raw_text_en="Live exposed 11kV wire sparking in floodwater!",
            urgency_tier=Complaint.UrgencyTier.P1,
            geo_point=Point(90.4143, 23.7925, srid=4326),
            admin_geo_code="30262619",
        )
        TieredSLAService.route_complaint(complaint=p1, target_seat_id=self.gro_seat.doptor_seat_id)
        with self.assertRaises(WorkflowTransitionError):
            GrievanceWorkflowEngine.request_transfer(
                complaint=p1,
                from_seat_id=self.gro_seat.doptor_seat_id,
                target_seat_id=self.wasa_gro_seat.doptor_seat_id,
                reason="Belongs to utility agency.",
                actor_id="OFF-GRO-1",
            )

        # P2 ticket: 1st transfer succeeds, 2nd locks into ARBITRATION_LOCKED
        TieredSLAService.route_complaint(
            complaint=self.complaint, target_seat_id=self.gro_seat.doptor_seat_id
        )
        r1 = GrievanceWorkflowEngine.request_transfer(
            complaint=self.complaint,
            from_seat_id=self.gro_seat.doptor_seat_id,
            target_seat_id=self.wasa_gro_seat.doptor_seat_id,
            reason="Water pipe belongs to Dhaka WASA.",
            actor_id="OFF-GRO-1",
        )
        self.assertEqual(r1["transfer_count"], 1)

        r2 = GrievanceWorkflowEngine.request_transfer(
            complaint=self.complaint,
            from_seat_id=self.wasa_gro_seat.doptor_seat_id,
            target_seat_id=self.gro_seat.doptor_seat_id,
            reason="Drainage belongs to DNCC.",
            actor_id="OFF-WASA-1",
        )
        self.assertEqual(r2["status"], Complaint.ComplaintStatus.ARBITRATION_LOCKED)
        self.complaint.refresh_from_db()
        self.assertTrue(self.complaint.is_arbitration_locked)
        self.assertEqual(ArbitrationCase.objects.filter(complaint=self.complaint).count(), 1)

    def test_officer_safeguards_procurement_hold_contest_and_unfounded_cleared(self):
        TieredSLAService.route_complaint(
            complaint=self.complaint, target_seat_id=self.gro_seat.doptor_seat_id
        )
        TieredSLAService.assign_field_worker(
            complaint=self.complaint,
            supervisor_seat_id=self.sup_seat.doptor_seat_id,
            field_worker_seat_id=self.fw_seat.doptor_seat_id,
            actor_id="OFF-SUP-1",
        )

        milestones = GrievanceWorkflowEngine.place_on_hold_procurement(
            complaint=self.complaint,
            seat_id=self.gro_seat.doptor_seat_id,
            actor_id="OFF-GRO-1",
            reference_type=CapitalMilestone.ReferenceType.EGP_TENDER,
            reference_id="EGP-2026-994821",
        )
        self.assertEqual(len(milestones), 4)
        self.assertTrue(self.complaint.workflow_tracker.is_sla_paused)

        # Complete execution -> resumes SLA & IN_PROGRESS
        GrievanceWorkflowEngine.advance_capital_milestone(
            complaint=self.complaint,
            stage=CapitalMilestone.Stage.EXECUTION,
            seat_id=self.gro_seat.doptor_seat_id,
            actor_id="OFF-GRO-1",
        )
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Complaint.ComplaintStatus.IN_PROGRESS)

        # Mark UNFOUNDED_CLEARED -> zero officer penalty + citizen strike
        outcome = GrievanceWorkflowEngine.mark_unfounded_cleared(
            complaint=self.complaint,
            adjudicator_user=self.adjudicator,
            reason="Field inspection with GPS photos proved complaint was fabricated.",
        )
        self.assertEqual(outcome["officer_apa_penalty"], 0.0)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.strike_count, 1)

    def test_escalation_daemon_80pct_warning_100pct_breach_ddcc_and_72h_autoclose(self):
        tracker, _ = TieredSLAService.route_complaint(
            complaint=self.complaint, target_seat_id=self.gro_seat.doptor_seat_id
        )
        # Simulate 85% elapsed -> Yellow warning
        now_85 = tracker.sla_started_at + timedelta(seconds=int(tracker.sla_total_seconds * 0.85))
        res_85 = SLAEscalationDaemon.run_sweep(now=now_85)
        self.assertEqual(res_85["yellow_warnings_80pct"], 1)
        self.assertEqual(
            EscalationEvent.objects.filter(
                complaint=self.complaint, event_type=EscalationEvent.EventType.YELLOW_WARNING_80
            ).count(),
            1,
        )

        # Simulate Tier-3 breach -> DDCC Agenda Item created
        self.complaint.escalation_level = 2
        self.complaint.save(update_fields=["escalation_level"])
        now_110 = tracker.sla_started_at + timedelta(seconds=int(tracker.sla_total_seconds * 1.10))
        res_110 = SLAEscalationDaemon.run_sweep(now=now_110)
        self.assertEqual(res_110["sla_breaches_escalated"], 1)
        self.assertEqual(res_110["ddcc_items_created"], 1)
        self.assertEqual(DDCCAgendaItem.objects.filter(complaint=self.complaint).count(), 1)
        self.assertTrue(AuditLog.verify_chain()[0])
