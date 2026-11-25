"""
Celery Beat SLA Escalation Daemon (runs every 5 minutes).

Responsibilities:
  1. Auto-acknowledge ROUTED tickets within 1 hour if not manually acknowledged.
  2. Auto-close PENDING_CITIZEN_VERIFY tickets after 72h silence with an audit flag.
  3. At 80% SLA elapsed -> send Yellow Warning to Unit Supervisor.
  4. At 100% SLA breach -> auto-escalate up the 4-tier ladder:
       Tier 1: Field/Supervisor/GRO
       Tier 2: District DC / Executive Engineer
       Tier 3: Divisional Commissioner / DG  (+ surface to Monthly DDCC agenda)
       Tier 4: Ministry Secretary / Cabinet Cell
     and log APA scorecard impact + SHA-256 AuditLog entries.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.complaints.models import AuditLog, Complaint
from apps.organogram.models import DoptorSeat
from apps.organogram.services.seat_router import ZeroBlackHoleSeatRouter
from apps.workflow.models import DDCCAgendaItem, EscalationEvent, WorkflowTracker
from apps.workflow.services.sla_service import SLAConfig, TieredSLAService


class SLAEscalationDaemon:
    """Stateless sweep service executed every 5 minutes by Celery Beat."""

    TIER_APA_IMPACT = {
        1: -1.0,
        2: -2.5,
        3: -5.0,
        4: -10.0,
    }

    ACTIVE_SLA_STATUSES = (
        Complaint.ComplaintStatus.ROUTED,
        Complaint.ComplaintStatus.TRANSFERRED,
        Complaint.ComplaintStatus.IN_PROGRESS,
    )

    @classmethod
    def run_sweep(cls, now=None) -> dict[str, int]:
        now = now or timezone.now()
        counts = {
            "auto_acknowledged": cls._sweep_auto_acknowledgements(now),
            "auto_closed_72h": cls._sweep_72h_citizen_auto_close(now),
            "yellow_warnings_80pct": 0,
            "sla_breaches_escalated": 0,
            "ddcc_items_created": 0,
        }

        trackers = (
            WorkflowTracker.objects.select_related("complaint")
            .filter(
                complaint__status__in=cls.ACTIVE_SLA_STATUSES,
                sla_paused_at__isnull=True,
            )
            .iterator(chunk_size=200)
        )

        for tracker in trackers:
            ratio = tracker.elapsed_ratio(now=now)
            if ratio >= 1.0:
                ddcc_created = cls._escalate_breach(tracker, now)
                counts["sla_breaches_escalated"] += 1
                if ddcc_created:
                    counts["ddcc_items_created"] += 1
            elif ratio >= SLAConfig.YELLOW_WARNING_THRESHOLD and tracker.yellow_warning_sent_at is None:
                cls._issue_yellow_warning(tracker, now)
                counts["yellow_warnings_80pct"] += 1

        return counts

    @classmethod
    def _sweep_auto_acknowledgements(cls, now) -> int:
        cutoff = now - SLAConfig.AUTO_ACK_WINDOW
        pending = WorkflowTracker.objects.select_related("complaint").filter(
            acknowledged_at__isnull=True,
            sla_started_at__lte=cutoff,
            complaint__status=Complaint.ComplaintStatus.ROUTED,
        )
        count = 0
        for tracker in pending:
            TieredSLAService.acknowledge_receipt(
                complaint=tracker.complaint,
                actor_id="SYSTEM-SLA-DAEMON",
                auto=True,
            )
            count += 1
        return count

    @classmethod
    def _sweep_72h_citizen_auto_close(cls, now) -> int:
        expired = WorkflowTracker.objects.select_related("complaint").filter(
            complaint__status=Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY,
            citizen_verify_deadline_at__lte=now,
            auto_closed_audit_flag=False,
        )
        count = 0
        for tracker in expired:
            with transaction.atomic():
                complaint = tracker.complaint
                complaint.status = Complaint.ComplaintStatus.CLOSED
                complaint.save(update_fields=["status", "updated_at"])

                tracker.auto_closed_audit_flag = True
                tracker.save(update_fields=["auto_closed_audit_flag", "updated_at"])

                AuditLog.objects.create(
                    complaint=complaint,
                    actor_id="SYSTEM-SLA-DAEMON",
                    actor_role="SYSTEM",
                    action="CITIZEN_VERIFY_72H_AUTO_CLOSED",
                    entity_type="Complaint",
                    entity_id=str(complaint.complaint_id),
                    payload={
                        "auto_closed_audit_flag": True,
                        "deadline_at": tracker.citizen_verify_deadline_at.isoformat(),
                    },
                )
            count += 1
        return count

    @classmethod
    @transaction.atomic
    def _issue_yellow_warning(cls, tracker: WorkflowTracker, now) -> EscalationEvent:
        complaint = tracker.complaint
        active = complaint.assignments.filter(is_active=True).first()
        seat_id = active.doptor_seat_id if active else ""

        tracker.yellow_warning_sent_at = now
        tracker.save(update_fields=["yellow_warning_sent_at", "updated_at"])

        event = EscalationEvent.objects.create(
            complaint=complaint,
            event_type=EscalationEvent.EventType.YELLOW_WARNING_80,
            escalation_tier=max(1, complaint.escalation_level or 1),
            from_seat_id=seat_id,
            to_seat_id=seat_id,
            apa_scorecard_impact=0.0,
            notes="80% statutory SLA elapsed; Yellow Warning issued to Unit Supervisor.",
        )

        AuditLog.objects.create(
            complaint=complaint,
            actor_id="SYSTEM-SLA-DAEMON",
            actor_seat_id=seat_id,
            actor_role="SYSTEM",
            action="SLA_80PCT_YELLOW_WARNING",
            entity_type="EscalationEvent",
            entity_id=str(event.event_id),
            payload={"elapsed_ratio": round(tracker.elapsed_ratio(now=now), 3)},
        )
        return event

    @classmethod
    @transaction.atomic
    def _escalate_breach(cls, tracker: WorkflowTracker, now) -> bool:
        complaint = tracker.complaint
        next_tier = min(4, (complaint.escalation_level or 0) + 1)
        active = complaint.assignments.filter(is_active=True).first()
        from_seat_id = active.doptor_seat_id if active else ""
        to_seat_id = cls._resolve_escalation_target_seat(from_seat_id, next_tier, complaint.admin_geo_code)

        complaint.escalation_level = next_tier
        complaint.save(update_fields=["escalation_level", "updated_at"])

        if to_seat_id and DoptorSeat.objects.filter(doptor_seat_id=to_seat_id).exists():
            ZeroBlackHoleSeatRouter().assign_complaint_to_seat(
                complaint=complaint, target_seat_id=to_seat_id, fire_hr_alert=False
            )

        apa_delta = cls.TIER_APA_IMPACT.get(next_tier, -2.5)
        ddcc_flagged = next_tier >= EscalationEvent.EscalationTier.TIER_3_DIVISIONAL

        event = EscalationEvent.objects.create(
            complaint=complaint,
            event_type=EscalationEvent.EventType.SLA_BREACH_100,
            escalation_tier=next_tier,
            from_seat_id=from_seat_id,
            to_seat_id=to_seat_id,
            apa_scorecard_impact=apa_delta,
            ddcc_flagged=ddcc_flagged,
            notes=f"100% SLA breach auto-escalated to Tier {next_tier}.",
        )

        ddcc_created = False
        if ddcc_flagged:
            agenda_month = now.strftime("%Y-%m")
            district_code = (complaint.admin_geo_code or "3026")[:4]
            _item, ddcc_created = DDCCAgendaItem.objects.get_or_create(
                complaint=complaint,
                agenda_month=agenda_month,
                defaults={
                    "escalation_event": event,
                    "district_bbs_code": district_code,
                    "summary": (
                        f"Tier-{next_tier} SLA breach on {complaint.tracking_code} "
                        f"({complaint.urgency_tier}) escalated from {from_seat_id or 'UNASSIGNED'}."
                    ),
                },
            )

        AuditLog.objects.create(
            complaint=complaint,
            actor_id="SYSTEM-SLA-DAEMON",
            actor_seat_id=to_seat_id,
            actor_role="SYSTEM",
            action="SLA_100PCT_BREACH_AUTO_ESCALATED",
            entity_type="EscalationEvent",
            entity_id=str(event.event_id),
            payload={
                "escalation_tier": next_tier,
                "from_seat_id": from_seat_id,
                "to_seat_id": to_seat_id,
                "apa_scorecard_impact": apa_delta,
                "ddcc_flagged": ddcc_flagged,
            },
        )
        return ddcc_created

    @staticmethod
    def _resolve_escalation_target_seat(from_seat_id: str, next_tier: int, admin_geo_code: str) -> str:
        if from_seat_id:
            seat = DoptorSeat.objects.select_related("parent_seat").filter(
                doptor_seat_id=from_seat_id
            ).first()
            if seat and seat.parent_seat:
                return seat.parent_seat.doptor_seat_id

        prefix = (admin_geo_code or "3026")[:4]
        tier_defaults = {
            1: f"SEAT-GRO-{prefix}",
            2: f"SEAT-DC-EXEC-{prefix}",
            3: f"SEAT-DIVCOMM-DG-{prefix[:2]}",
            4: "SEAT-CABINET-SEC-NAT",
        }
        return tier_defaults.get(next_tier, "SEAT-CABINET-SEC-NAT")
