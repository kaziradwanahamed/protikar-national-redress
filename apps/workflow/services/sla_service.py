"""Tiered SLA & Chain-of-Command Service for Bangladesh National Grievance Redress."""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.complaints.models import AuditLog, Complaint, TicketAssignment
from apps.organogram.models import RoleLevel
from apps.organogram.services.seat_router import ZeroBlackHoleSeatRouter
from apps.workflow.models import WorkflowTracker


class SLAConfig:
    """Statutory SLA tiers and governance timing constants."""

    P1_DURATION = timedelta(hours=4)
    P2_DURATION = timedelta(hours=48)
    P3_MIN_DAYS = 7
    P3_DEFAULT_DAYS = 10
    P3_MAX_DAYS = 15
    P4_DURATION = timedelta(days=30)

    AUTO_ACK_WINDOW = timedelta(hours=1)
    FIELD_WORKER_SLA_FRACTION = 0.70
    TRANSFER_WINDOW_FRACTION = 0.15
    P1_TRANSFER_MAX_WINDOW = timedelta(minutes=30)
    CITIZEN_VERIFY_WINDOW = timedelta(hours=72)
    OFFICER_REBUTTAL_WINDOW = timedelta(hours=48)
    ARBITRATION_DECISION_SLA = timedelta(hours=24)
    ARBITRATION_P1_DECISION_SLA = timedelta(hours=2)
    YELLOW_WARNING_THRESHOLD = 0.80


class TieredSLAService:
    """Calculates statutory SLAs, routes initial tickets, and assigns field workers at 70% SLA."""

    @staticmethod
    def get_sla_duration(urgency_tier: str, p3_days: int = SLAConfig.P3_DEFAULT_DAYS) -> timedelta:
        if urgency_tier == Complaint.UrgencyTier.P1:
            return SLAConfig.P1_DURATION
        if urgency_tier == Complaint.UrgencyTier.P2:
            return SLAConfig.P2_DURATION
        if urgency_tier == Complaint.UrgencyTier.P3:
            clamped_days = max(SLAConfig.P3_MIN_DAYS, min(SLAConfig.P3_MAX_DAYS, int(p3_days)))
            return timedelta(days=clamped_days)
        if urgency_tier == Complaint.UrgencyTier.P4:
            return SLAConfig.P4_DURATION
        return timedelta(days=SLAConfig.P3_DEFAULT_DAYS)

    @classmethod
    @transaction.atomic
    def route_complaint(
        cls,
        *,
        complaint: Complaint,
        target_seat_id: str,
        actor_id: str = "SYSTEM-ROUTER",
        p3_days: int = SLAConfig.P3_DEFAULT_DAYS,
    ) -> tuple[WorkflowTracker, TicketAssignment]:
        now = timezone.now()
        duration = cls.get_sla_duration(complaint.urgency_tier, p3_days=p3_days)
        deadline = now + duration

        complaint.sla_deadline_at = deadline
        complaint.status = Complaint.ComplaintStatus.ROUTED
        complaint.save(update_fields=["sla_deadline_at", "status", "updated_at"])

        tracker, _ = WorkflowTracker.objects.update_or_create(
            complaint=complaint,
            defaults={
                "sla_started_at": now,
                "sla_total_seconds": int(duration.total_seconds()),
            },
        )

        assignment, resolution = ZeroBlackHoleSeatRouter().assign_complaint_to_seat(
            complaint=complaint,
            target_seat_id=target_seat_id,
            due_at=deadline,
        )
        # Keep statutory status ROUTED after seat router assignment
        if complaint.status != Complaint.ComplaintStatus.ROUTED:
            complaint.status = Complaint.ComplaintStatus.ROUTED
            complaint.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=resolution.resolved_seat.doptor_seat_id,
            actor_role=resolution.resolved_seat.role_level,
            action="WORKFLOW_ROUTED_SLA_STARTED",
            entity_type="Complaint",
            entity_id=str(complaint.complaint_id),
            payload={
                "urgency_tier": complaint.urgency_tier,
                "sla_total_seconds": tracker.sla_total_seconds,
                "sla_deadline_at": deadline.isoformat(),
                "resolved_seat_id": resolution.resolved_seat.doptor_seat_id,
            },
        )
        return tracker, assignment

    @classmethod
    @transaction.atomic
    def acknowledge_receipt(
        cls,
        *,
        complaint: Complaint,
        actor_id: str,
        actor_seat_id: str = "",
        auto: bool = False,
    ) -> WorkflowTracker:
        tracker = complaint.workflow_tracker
        if tracker.acknowledged_at is not None:
            return tracker

        now = timezone.now()
        tracker.acknowledged_at = now
        tracker.auto_acknowledged = auto
        if complaint.urgency_tier == Complaint.UrgencyTier.P1 and tracker.p1_accepted_at is None:
            tracker.p1_accepted_at = now
        tracker.save(update_fields=["acknowledged_at", "auto_acknowledged", "p1_accepted_at", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=actor_seat_id,
            actor_role="SYSTEM" if auto else RoleLevel.GRO,
            action="DEPARTMENT_AUTO_ACKNOWLEDGED" if auto else "DEPARTMENT_ACKNOWLEDGED",
            entity_type="WorkflowTracker",
            entity_id=str(tracker.tracker_id),
            payload={"auto_acknowledged": auto, "acknowledged_at": now.isoformat()},
        )
        return tracker

    @classmethod
    @transaction.atomic
    def assign_field_worker(
        cls,
        *,
        complaint: Complaint,
        supervisor_seat_id: str,
        field_worker_seat_id: str,
        actor_id: str,
    ) -> TicketAssignment:
        tracker = complaint.workflow_tracker
        now = timezone.now()
        sub_deadline = tracker.sla_started_at + timedelta(
            seconds=int(tracker.sla_total_seconds * SLAConfig.FIELD_WORKER_SLA_FRACTION)
        )

        assignment, resolution = ZeroBlackHoleSeatRouter().assign_complaint_to_seat(
            complaint=complaint,
            target_seat_id=field_worker_seat_id,
            due_at=sub_deadline,
        )

        tracker.field_worker_sub_deadline_at = sub_deadline
        if tracker.acknowledged_at is None:
            tracker.acknowledged_at = now
        if complaint.urgency_tier == Complaint.UrgencyTier.P1 and tracker.p1_accepted_at is None:
            tracker.p1_accepted_at = now
        tracker.save(
            update_fields=[
                "field_worker_sub_deadline_at",
                "acknowledged_at",
                "p1_accepted_at",
                "updated_at",
            ]
        )

        complaint.status = Complaint.ComplaintStatus.IN_PROGRESS
        complaint.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=supervisor_seat_id,
            actor_role=RoleLevel.SUPERVISOR,
            action="FIELD_WORKER_ASSIGNED_70PCT_SLA",
            entity_type="TicketAssignment",
            entity_id=str(assignment.assignment_id),
            payload={
                "field_worker_seat_id": resolution.resolved_seat.doptor_seat_id,
                "sub_deadline_at": sub_deadline.isoformat(),
                "sla_fraction": SLAConfig.FIELD_WORKER_SLA_FRACTION,
            },
        )
        return assignment
