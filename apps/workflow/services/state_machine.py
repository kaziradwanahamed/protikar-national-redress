"""
Statutory Workflow State Machine & Governance Safeguards.

Lifecycle:
  SUBMITTED -> ROUTED -> [TRANSFERRED (max 2) -> ARBITRATION_LOCKED] -> IN_PROGRESS
  -> [ON_HOLD_PROCUREMENT | DISASTER_SLA_SUSPENDED] -> PENDING_CITIZEN_VERIFY
  -> [CONTESTED_BY_OFFICER | UNFOUNDED_CLEARED] -> CLOSED

Every transition writes a SHA-256 hash-chained AuditLog entry.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import CitizenProfile, User
from apps.complaints.models import AuditLog, Complaint, ResolutionReport, TicketAssignment
from apps.organogram.models import DoptorSeat, RoleLevel
from apps.organogram.services.seat_router import ZeroBlackHoleSeatRouter
from apps.workflow.models import ArbitrationCase, CapitalMilestone, EscalationEvent, WorkflowTracker
from apps.workflow.services.sla_service import SLAConfig


class WorkflowTransitionError(ValueError):
    """Raised when a requested statutory state transition violates governance rules."""


class WorkflowPermissionError(PermissionError):
    """Raised when an actor lacks authority for a state transition (e.g. Field Worker closing)."""


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    Complaint.ComplaintStatus.SUBMITTED: {
        Complaint.ComplaintStatus.ROUTED,
        Complaint.ComplaintStatus.UNFOUNDED_CLEARED,
    },
    Complaint.ComplaintStatus.ROUTED: {
        Complaint.ComplaintStatus.TRANSFERRED,
        Complaint.ComplaintStatus.ARBITRATION_LOCKED,
        Complaint.ComplaintStatus.IN_PROGRESS,
        Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED,
        Complaint.ComplaintStatus.UNFOUNDED_CLEARED,
    },
    Complaint.ComplaintStatus.TRANSFERRED: {
        Complaint.ComplaintStatus.ROUTED,
        Complaint.ComplaintStatus.ARBITRATION_LOCKED,
        Complaint.ComplaintStatus.IN_PROGRESS,
    },
    Complaint.ComplaintStatus.ARBITRATION_LOCKED: {
        Complaint.ComplaintStatus.ROUTED,
        Complaint.ComplaintStatus.IN_PROGRESS,
    },
    Complaint.ComplaintStatus.IN_PROGRESS: {
        Complaint.ComplaintStatus.ON_HOLD_PROCUREMENT,
        Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED,
        Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY,
        Complaint.ComplaintStatus.UNFOUNDED_CLEARED,
    },
    Complaint.ComplaintStatus.ON_HOLD_PROCUREMENT: {
        Complaint.ComplaintStatus.IN_PROGRESS,
        Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY,
    },
    Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED: {
        Complaint.ComplaintStatus.ROUTED,
        Complaint.ComplaintStatus.IN_PROGRESS,
    },
    Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY: {
        Complaint.ComplaintStatus.CLOSED,
        Complaint.ComplaintStatus.IN_PROGRESS,
        Complaint.ComplaintStatus.CONTESTED_BY_OFFICER,
        Complaint.ComplaintStatus.UNFOUNDED_CLEARED,
    },
    Complaint.ComplaintStatus.CONTESTED_BY_OFFICER: {
        Complaint.ComplaintStatus.CLOSED,
        Complaint.ComplaintStatus.UNFOUNDED_CLEARED,
        Complaint.ComplaintStatus.IN_PROGRESS,
    },
    Complaint.ComplaintStatus.UNFOUNDED_CLEARED: {
        Complaint.ComplaintStatus.CLOSED,
    },
    Complaint.ComplaintStatus.CLOSED: set(),
}


def _haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6_371_008.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GrievanceWorkflowEngine:
    """Enforces statutory transitions, Two-Key verification, transfer caps, and officer fairness."""

    MAX_RESOLUTION_GPS_DISTANCE_M = 100.0
    MAX_TRANSFERS = 2

    @staticmethod
    def assert_transition_allowed(complaint: Complaint, target_status: str) -> None:
        allowed = ALLOWED_TRANSITIONS.get(complaint.status, set())
        if target_status not in allowed:
            raise WorkflowTransitionError(
                f"Illegal statutory transition: {complaint.status} -> {target_status}."
            )

    @staticmethod
    def compute_postgis_distance_m(complaint: Complaint, after_lon: float, after_lat: float) -> float:
        """
        Compute meter-accurate geodesic distance between complaint.geo_point and the
        geo-tagged 'After' photo using PostGIS ST_Distance on geography=True PointField.
        """
        if complaint.geo_point is None:
            raise WorkflowTransitionError(
                "Complaint lacks geo_point; cannot run 100m PostGIS resolution gate."
            )
        photo_point = Point(float(after_lon), float(after_lat), srid=4326)
        annotated = (
            Complaint.objects.filter(pk=complaint.pk)
            .annotate(dist=Distance("geo_point", photo_point))
            .values_list("dist", flat=True)
            .first()
        )
        if annotated is not None:
            return round(float(annotated.m), 2)
        return round(
            _haversine_meters(
                complaint.geo_point.x, complaint.geo_point.y, photo_point.x, photo_point.y
            ),
            2,
        )

    @staticmethod
    def assert_not_direct_field_close(actor_role: str, target_status: str) -> None:
        if actor_role == RoleLevel.FIELD_WORKER and target_status == Complaint.ComplaintStatus.CLOSED:
            raise WorkflowPermissionError(
                "Two-Key Verification Gate: Field workers cannot directly close complaints."
            )

    # -----------------------------------------------------------------------
    # 1. Two-Key Verification Gate
    # -----------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def submit_resolution_for_verification(
        cls,
        *,
        complaint: Complaint,
        submitted_by_seat: str,
        supervisor_signoff_seat: str,
        work_summary: str,
        after_photo_urls: list[str],
        after_lon: float,
        after_lat: float,
        actor_id: str,
    ) -> ResolutionReport:
        cls.assert_transition_allowed(complaint, Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY)

        if not work_summary or len(work_summary.strip()) < 10:
            raise WorkflowTransitionError("Detailed work_summary (>=10 chars) is required.")
        if not after_photo_urls:
            raise WorkflowTransitionError("At least one geo-tagged 'After' photo URL is required.")
        if not supervisor_signoff_seat:
            raise WorkflowTransitionError("Supervisor digital sign-off seat ID is required.")

        sup_seat = DoptorSeat.objects.filter(doptor_seat_id=supervisor_signoff_seat).first()
        if sup_seat and sup_seat.role_level == RoleLevel.FIELD_WORKER:
            raise WorkflowPermissionError(
                "Supervisor digital sign-off cannot be issued by a FIELD_WORKER seat."
            )

        distance_m = cls.compute_postgis_distance_m(complaint, after_lon, after_lat)
        if distance_m > cls.MAX_RESOLUTION_GPS_DISTANCE_M:
            raise WorkflowTransitionError(
                f"Two-Key GPS Gate failed: 'After' photo is {distance_m}m from complaint "
                f"location (maximum allowed is {cls.MAX_RESOLUTION_GPS_DISTANCE_M}m)."
            )

        report = ResolutionReport.objects.create(
            complaint=complaint,
            submitted_by_seat=submitted_by_seat,
            work_summary=work_summary.strip(),
            after_photo_urls=after_photo_urls,
            gps_verified_dist_m=distance_m,
            citizen_verdict=ResolutionReport.CitizenVerdict.PENDING,
        )

        now = timezone.now()
        verify_deadline = now + SLAConfig.CITIZEN_VERIFY_WINDOW
        tracker = complaint.workflow_tracker
        tracker.pending_citizen_verify_at = now
        tracker.citizen_verify_deadline_at = verify_deadline
        tracker.save(
            update_fields=["pending_citizen_verify_at", "citizen_verify_deadline_at", "updated_at"]
        )

        complaint.status = Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY
        complaint.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=supervisor_signoff_seat,
            actor_role=RoleLevel.SUPERVISOR,
            action="RESOLUTION_SUBMITTED_PENDING_CITIZEN_VERIFY",
            entity_type="ResolutionReport",
            entity_id=str(report.report_id),
            payload={
                "submitted_by_seat": submitted_by_seat,
                "supervisor_signoff_seat": supervisor_signoff_seat,
                "gps_verified_dist_m": distance_m,
                "citizen_verify_deadline_at": verify_deadline.isoformat(),
            },
        )
        return report

    @classmethod
    @transaction.atomic
    def record_citizen_verdict(
        cls,
        *,
        complaint: Complaint,
        verdict: str,
        citizen_actor_id: str,
        feedback: str = "",
        evidence_urls: list[str] | None = None,
    ) -> ResolutionReport:
        if complaint.status != Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY:
            raise WorkflowTransitionError(
                f"Citizen verdict only allowed in PENDING_CITIZEN_VERIFY (current: {complaint.status})."
            )

        report = complaint.resolution_reports.order_by("-submitted_at").first()
        if not report:
            raise WorkflowTransitionError("No resolution report exists for this complaint.")

        if verdict == ResolutionReport.CitizenVerdict.ACCEPTED:
            report.citizen_verdict = ResolutionReport.CitizenVerdict.ACCEPTED
            report.citizen_feedback = feedback
            report.save(update_fields=["citizen_verdict", "citizen_feedback"])

            complaint.status = Complaint.ComplaintStatus.CLOSED
            complaint.save(update_fields=["status", "updated_at"])

            AuditLog.objects.create(
                complaint=complaint,
                actor_id=citizen_actor_id,
                actor_role="CITIZEN",
                action="CITIZEN_ACCEPTED_CLOSED",
                entity_type="Complaint",
                entity_id=str(complaint.complaint_id),
                payload={"report_id": str(report.report_id), "feedback": feedback},
            )
            return report

        if verdict == ResolutionReport.CitizenVerdict.REJECTED:
            if not feedback and not evidence_urls:
                raise WorkflowTransitionError(
                    "Citizen rejection requires feedback or supporting evidence."
                )
            report.citizen_verdict = ResolutionReport.CitizenVerdict.REJECTED
            report.citizen_feedback = feedback
            report.save(update_fields=["citizen_verdict", "citizen_feedback"])

            complaint.status = Complaint.ComplaintStatus.IN_PROGRESS
            complaint.escalation_level = min(4, complaint.escalation_level + 1)
            complaint.save(update_fields=["status", "escalation_level", "updated_at"])

            # Escalate 1 level up the seat chain if available
            active_assignment = complaint.assignments.filter(is_active=True).first()
            from_seat_id = active_assignment.doptor_seat_id if active_assignment else ""
            to_seat_id = from_seat_id
            if from_seat_id:
                current_seat = (
                    DoptorSeat.objects.select_related("parent_seat")
                    .filter(doptor_seat_id=from_seat_id)
                    .first()
                )
                if current_seat and current_seat.parent_seat:
                    ZeroBlackHoleSeatRouter().assign_complaint_to_seat(
                        complaint=complaint,
                        target_seat_id=current_seat.parent_seat.doptor_seat_id,
                    )
                    to_seat_id = current_seat.parent_seat.doptor_seat_id

            EscalationEvent.objects.create(
                complaint=complaint,
                event_type=EscalationEvent.EventType.CITIZEN_REJECTION,
                escalation_tier=max(1, complaint.escalation_level),
                from_seat_id=from_seat_id,
                to_seat_id=to_seat_id,
                notes=feedback,
            )

            AuditLog.objects.create(
                complaint=complaint,
                actor_id=citizen_actor_id,
                actor_role="CITIZEN",
                action="CITIZEN_REJECTED_REOPENED_ESCALATED",
                entity_type="Complaint",
                entity_id=str(complaint.complaint_id),
                payload={
                    "report_id": str(report.report_id),
                    "new_escalation_level": complaint.escalation_level,
                    "escalated_to_seat": to_seat_id,
                    "evidence_urls": evidence_urls or [],
                },
            )
            return report

        raise WorkflowTransitionError(f"Unsupported citizen verdict: {verdict}")

    # -----------------------------------------------------------------------
    # 2. Anti-Gaming Transfer Cap, 15% SLA Window & Jurisdiction Arbitration
    # -----------------------------------------------------------------------
    @staticmethod
    def _resolve_arbitrator(
        from_seat_id: str, to_seat_id: str, admin_geo_code: str
    ) -> tuple[str, str]:
        from_seat = DoptorSeat.objects.select_related("office").filter(doptor_seat_id=from_seat_id).first()
        to_seat = DoptorSeat.objects.select_related("office").filter(doptor_seat_id=to_seat_id).first()

        if from_seat and to_seat:
            same_upazila = (
                from_seat.office.upazila_code
                and from_seat.office.upazila_code == to_seat.office.upazila_code
                and from_seat.office.district_code == to_seat.office.district_code
            )
            if same_upazila:
                return (
                    ArbitrationCase.JurisdictionScope.UPAZILA_UNO,
                    f"SEAT-UNO-ARB-{from_seat.office.bbs_geo_code or 'UPZ'}",
                )
            same_district = (
                from_seat.office.district_code
                and from_seat.office.district_code == to_seat.office.district_code
                and from_seat.office.ministry_code == to_seat.office.ministry_code
            )
            if same_district:
                return (
                    ArbitrationCase.JurisdictionScope.DISTRICT_DC,
                    f"SEAT-DC-ARB-{from_seat.office.district_code}",
                )

        return (
            ArbitrationCase.JurisdictionScope.DIVISIONAL_CABINET,
            f"SEAT-CABINET-ARB-{(admin_geo_code or 'NAT')[:2]}",
        )

    @classmethod
    @transaction.atomic
    def request_transfer(
        cls,
        *,
        complaint: Complaint,
        from_seat_id: str,
        target_seat_id: str,
        reason: str,
        actor_id: str,
        now=None,
    ) -> dict[str, Any]:
        now = now or timezone.now()
        if complaint.is_arbitration_locked or complaint.transfer_count >= cls.MAX_TRANSFERS:
            raise WorkflowTransitionError(
                "Complaint is arbitration-locked (transfer_count >= 2); further transfers forbidden."
            )

        tracker = complaint.workflow_tracker

        # P1 Accept-First, Dispute-Later enforcement
        if complaint.urgency_tier == Complaint.UrgencyTier.P1 and tracker.p1_accepted_at is None:
            raise WorkflowTransitionError(
                "P1 Life-Safety Rule (Accept-First, Dispute-Later): "
                "Officer must accept and stabilize the emergency before disputing jurisdiction."
            )

        # Enforce transfer only within first 15% of SLA (30 mins hard cap for P1)
        elapsed_sec = tracker.elapsed_active_seconds(now=now)
        max_window_sec = tracker.sla_total_seconds * SLAConfig.TRANSFER_WINDOW_FRACTION
        if complaint.urgency_tier == Complaint.UrgencyTier.P1:
            max_window_sec = min(max_window_sec, SLAConfig.P1_TRANSFER_MAX_WINDOW.total_seconds())
        if elapsed_sec > max_window_sec:
            raise WorkflowTransitionError(
                f"Transfer window expired: elapsed {int(elapsed_sec)}s exceeds allowed "
                f"{int(max_window_sec)}s window (first 15% of SLA; 30m max for P1)."
            )

        new_count = complaint.transfer_count + 1
        complaint.transfer_count = new_count

        # 2nd refusal -> Lock into ARBITRATION_LOCKED & route to Jurisdiction Arbitrator
        if new_count >= cls.MAX_TRANSFERS:
            scope, arb_seat_id = cls._resolve_arbitrator(
                from_seat_id, target_seat_id, complaint.admin_geo_code
            )
            arb_sla = (
                SLAConfig.ARBITRATION_P1_DECISION_SLA
                if complaint.urgency_tier == Complaint.UrgencyTier.P1
                else SLAConfig.ARBITRATION_DECISION_SLA
            )
            arb_deadline = now + arb_sla

            complaint.is_arbitration_locked = True
            complaint.status = Complaint.ComplaintStatus.ARBITRATION_LOCKED
            complaint.save(
                update_fields=["transfer_count", "is_arbitration_locked", "status", "updated_at"]
            )

            arb_case = ArbitrationCase.objects.create(
                complaint=complaint,
                jurisdiction_scope=scope,
                arbitrator_seat_id=arb_seat_id,
                decision_sla_deadline_at=arb_deadline,
                disputing_seats=[from_seat_id, target_seat_id],
            )

            AuditLog.objects.create(
                complaint=complaint,
                actor_id=actor_id,
                actor_seat_id=from_seat_id,
                actor_role=RoleLevel.GRO,
                action="TRANSFER_CAP_HIT_ARBITRATION_LOCKED",
                entity_type="ArbitrationCase",
                entity_id=str(arb_case.arbitration_id),
                payload={
                    "transfer_count": new_count,
                    "jurisdiction_scope": scope,
                    "arbitrator_seat_id": arb_seat_id,
                    "decision_sla_deadline_at": arb_deadline.isoformat(),
                    "reason": reason,
                },
            )
            return {
                "status": Complaint.ComplaintStatus.ARBITRATION_LOCKED,
                "arbitration_id": str(arb_case.arbitration_id),
                "jurisdiction_scope": scope,
                "arbitrator_seat_id": arb_seat_id,
                "decision_sla_deadline_at": arb_deadline.isoformat(),
            }

        # 1st transfer -> route cleanly to target_seat_id via Zero-Black-Hole router
        complaint.status = Complaint.ComplaintStatus.TRANSFERRED
        complaint.save(update_fields=["transfer_count", "status", "updated_at"])

        assignment, resolution = ZeroBlackHoleSeatRouter().assign_complaint_to_seat(
            complaint=complaint, target_seat_id=target_seat_id
        )
        complaint.status = Complaint.ComplaintStatus.ROUTED
        complaint.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=from_seat_id,
            actor_role=RoleLevel.GRO,
            action="COMPLAINT_TRANSFERRED",
            entity_type="TicketAssignment",
            entity_id=str(assignment.assignment_id),
            payload={
                "transfer_count": new_count,
                "from_seat_id": from_seat_id,
                "resolved_seat_id": resolution.resolved_seat.doptor_seat_id,
                "reason": reason,
            },
        )
        return {
            "status": Complaint.ComplaintStatus.ROUTED,
            "transfer_count": new_count,
            "resolved_seat_id": resolution.resolved_seat.doptor_seat_id,
        }

    # -----------------------------------------------------------------------
    # 3. Officer Fairness Safeguards
    # -----------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def place_on_hold_procurement(
        cls,
        *,
        complaint: Complaint,
        seat_id: str,
        actor_id: str,
        reference_type: str,
        reference_id: str,
        notes: str = "",
    ) -> list[CapitalMilestone]:
        cls.assert_transition_allowed(complaint, Complaint.ComplaintStatus.ON_HOLD_PROCUREMENT)
        if not reference_id or len(reference_id.strip()) < 4:
            raise WorkflowTransitionError(
                "A verified e-GP Tender ID or D-Nothi Reference is required to pause SLA."
            )

        now = timezone.now()
        tracker = complaint.workflow_tracker
        if tracker.sla_paused_at is None:
            tracker.sla_paused_at = now
            tracker.save(update_fields=["sla_paused_at", "updated_at"])

        complaint.status = Complaint.ComplaintStatus.ON_HOLD_PROCUREMENT
        complaint.hold_reason_code = (
            Complaint.HoldReasonCode.EGP_TENDER
            if reference_type == CapitalMilestone.ReferenceType.EGP_TENDER
            else Complaint.HoldReasonCode.BUDGET_APPROVAL
        )
        complaint.hold_reference_id = reference_id.strip()
        complaint.save(
            update_fields=["status", "hold_reason_code", "hold_reference_id", "updated_at"]
        )

        stages = [
            (CapitalMilestone.Stage.BUDGET_APPROVED, 1, True),
            (
                CapitalMilestone.Stage.EGP_TENDER_FLOATED,
                2,
                reference_type == CapitalMilestone.ReferenceType.EGP_TENDER,
            ),
            (CapitalMilestone.Stage.WORK_ORDER_ISSUED, 3, False),
            (CapitalMilestone.Stage.EXECUTION, 4, False),
        ]
        milestones: list[CapitalMilestone] = []
        for stage, order, done in stages:
            m, _ = CapitalMilestone.objects.update_or_create(
                complaint=complaint,
                stage=stage,
                defaults={
                    "stage_order": order,
                    "reference_type": reference_type,
                    "reference_id": reference_id.strip(),
                    "notes": notes if order == 1 else "",
                    "is_completed": done,
                    "completed_at": now if done else None,
                    "updated_by_seat": seat_id,
                },
            )
            milestones.append(m)

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=seat_id,
            actor_role=RoleLevel.GRO,
            action="SLA_PAUSED_ON_HOLD_PROCUREMENT",
            entity_type="Complaint",
            entity_id=str(complaint.complaint_id),
            payload={
                "reference_type": reference_type,
                "reference_id": reference_id.strip(),
                "milestones_initialized": [m.stage for m in milestones],
            },
        )
        return milestones

    @classmethod
    @transaction.atomic
    def advance_capital_milestone(
        cls,
        *,
        complaint: Complaint,
        stage: str,
        seat_id: str,
        actor_id: str,
        notes: str = "",
    ) -> CapitalMilestone:
        milestone = CapitalMilestone.objects.get(complaint=complaint, stage=stage)
        now = timezone.now()
        milestone.is_completed = True
        milestone.completed_at = now
        milestone.notes = notes or milestone.notes
        milestone.updated_by_seat = seat_id
        milestone.save(
            update_fields=["is_completed", "completed_at", "notes", "updated_by_seat", "updated_at"]
        )

        # Resume SLA once physical EXECUTION starts/completes
        if stage == CapitalMilestone.Stage.EXECUTION:
            tracker = complaint.workflow_tracker
            if tracker.sla_paused_at is not None:
                paused_delta = int(max(0.0, (now - tracker.sla_paused_at).total_seconds()))
                tracker.sla_accumulated_pause_seconds += paused_delta
                tracker.sla_paused_at = None
                tracker.save(
                    update_fields=[
                        "sla_accumulated_pause_seconds",
                        "sla_paused_at",
                        "updated_at",
                    ]
                )
                if complaint.sla_deadline_at:
                    complaint.sla_deadline_at = complaint.sla_deadline_at + timedelta(
                        seconds=paused_delta
                    )
            complaint.status = Complaint.ComplaintStatus.IN_PROGRESS
            complaint.save(update_fields=["status", "sla_deadline_at", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=seat_id,
            actor_role=RoleLevel.GRO,
            action="CAPITAL_MILESTONE_COMPLETED",
            entity_type="CapitalMilestone",
            entity_id=str(milestone.milestone_id),
            payload={"stage": stage, "notes": notes},
        )
        return milestone

    @classmethod
    @transaction.atomic
    def contest_by_officer(
        cls,
        *,
        complaint: Complaint,
        seat_id: str,
        actor_id: str,
        rebuttal_url: str,
        notes: str = "",
    ) -> WorkflowTracker:
        cls.assert_transition_allowed(complaint, Complaint.ComplaintStatus.CONTESTED_BY_OFFICER)
        if not rebuttal_url:
            raise WorkflowTransitionError(
                "Counter-evidence URL (officer_rebuttal_url) is required to contest."
            )

        now = timezone.now()
        deadline = now + SLAConfig.OFFICER_REBUTTAL_WINDOW
        tracker = complaint.workflow_tracker
        tracker.officer_rebuttal_deadline_at = deadline
        tracker.save(update_fields=["officer_rebuttal_deadline_at", "updated_at"])

        complaint.status = Complaint.ComplaintStatus.CONTESTED_BY_OFFICER
        complaint.officer_rebuttal_url = rebuttal_url
        complaint.save(update_fields=["status", "officer_rebuttal_url", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=seat_id,
            actor_role=RoleLevel.GRO,
            action="CONTESTED_BY_OFFICER_48H_REPLY",
            entity_type="Complaint",
            entity_id=str(complaint.complaint_id),
            payload={
                "rebuttal_url": rebuttal_url,
                "rebuttal_deadline_at": deadline.isoformat(),
                "notes": notes,
            },
        )
        return tracker

    @classmethod
    @transaction.atomic
    def mark_unfounded_cleared(
        cls,
        *,
        complaint: Complaint,
        adjudicator_user: User,
        reason: str,
        strike_penalty: float = 25.0,
    ) -> dict[str, Any]:
        cls.assert_transition_allowed(complaint, Complaint.ComplaintStatus.UNFOUNDED_CLEARED)
        if not reason or len(reason.strip()) < 10:
            raise WorkflowTransitionError("Adjudication reason (>=10 chars) is required.")

        complaint.status = Complaint.ComplaintStatus.UNFOUNDED_CLEARED
        complaint.save(update_fields=["status", "updated_at"])

        citizen_strike_info = None
        profile = CitizenProfile.objects.filter(
            pseudonymous_public_hash=complaint.citizen_uct_hash
        ).first()
        if profile:
            profile.record_verified_false_filing(reason=reason.strip(), penalty=strike_penalty)
            citizen_strike_info = {
                "strike_count": profile.strike_count,
                "credibility_score": profile.credibility_score,
                "requires_manual_premoderation": profile.requires_manual_premoderation,
            }

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=str(adjudicator_user.id),
            actor_seat_id=adjudicator_user.doptor_seat_id or "APPELLATE-REVIEW",
            actor_role=adjudicator_user.doptor_role_level or RoleLevel.APPELLATE,
            action="UNFOUNDED_CLEARED_OFFICER_ZERO_PENALTY",
            entity_type="Complaint",
            entity_id=str(complaint.complaint_id),
            payload={
                "officer_apa_penalty": 0.0,
                "reason": reason.strip(),
                "citizen_strike_info": citizen_strike_info,
            },
        )
        return {
            "status": complaint.status,
            "officer_apa_penalty": 0.0,
            "citizen_strike_info": citizen_strike_info,
        }
