"""
Zero-Black-Hole Vacant Seat Fallback Router.

Ensures no citizen grievance is ever stranded on a vacant or transferred official's seat:
  1) If target Seat_X is occupied -> assign to primary seat's officer.
  2) If Seat_X is vacant -> route to `additional_charge_seat_id` (if occupied).
  3) If no occupied additional-charge seat -> auto-route to `immediate_supervisor_seat_id`
     and fire an automated Doptor HR vacancy alert + immutable AuditLog entry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from django.db import transaction

from apps.complaints.models import AuditLog, Complaint, TicketAssignment
from apps.organogram.models import DoptorSeat, DoptorVacancyAlert


logger = logging.getLogger(__name__)


class SeatRoutingError(ValueError):
    """Raised when no active, occupied seat can be found anywhere in the routing chain."""


@dataclass(frozen=True)
class SeatResolutionResult:
    requested_seat: DoptorSeat
    resolved_seat: DoptorSeat
    fallback_tier: str
    vacancy_alert: DoptorVacancyAlert | None = None


class ZeroBlackHoleSeatRouter:
    """Deterministic 3-tier seat router guaranteeing zero black-hole assignments."""

    MAX_SUPERVISOR_HOPS = 10

    def resolve_seat(
        self,
        *,
        target_seat_id: str,
        complaint_id=None,
        fire_hr_alert: bool = True,
    ) -> SeatResolutionResult:
        try:
            seat = DoptorSeat.objects.select_related(
                "office", "additional_charge_seat__office", "parent_seat__office"
            ).get(doptor_seat_id=target_seat_id)
        except DoptorSeat.DoesNotExist as exc:
            raise SeatRoutingError(f"Target Doptor seat '{target_seat_id}' does not exist.") from exc

        # Tier 1: Primary seat is occupied
        if seat.is_occupied:
            return SeatResolutionResult(
                requested_seat=seat,
                resolved_seat=seat,
                fallback_tier="PRIMARY_OCCUPIED",
                vacancy_alert=None,
            )

        # Tier 2: Vacant primary seat -> route to occupied additional_charge_seat
        addl = seat.additional_charge_seat
        if addl and addl.is_occupied:
            return SeatResolutionResult(
                requested_seat=seat,
                resolved_seat=addl,
                fallback_tier=DoptorVacancyAlert.FallbackTier.ADDITIONAL_CHARGE,
                vacancy_alert=None,
            )

        # Tier 3: Vacant with no occupied additional charge -> immediate supervisor + HR alert
        supervisor = self._find_occupied_supervisor(seat)
        if supervisor is None:
            alert = self._create_vacancy_alert(
                vacant_seat=seat,
                routed_to_seat=None,
                complaint_id=complaint_id,
                fallback_tier=DoptorVacancyAlert.FallbackTier.UNRESOLVED,
                fire_hr_alert=fire_hr_alert,
            )
            raise SeatRoutingError(
                f"Seat '{target_seat_id}' is vacant and has no occupied additional-charge or "
                f"supervisor seat (DoptorVacancyAlert={alert.alert_id})."
            )

        alert = self._create_vacancy_alert(
            vacant_seat=seat,
            routed_to_seat=supervisor,
            complaint_id=complaint_id,
            fallback_tier=DoptorVacancyAlert.FallbackTier.IMMEDIATE_SUPERVISOR,
            fire_hr_alert=fire_hr_alert,
        )
        return SeatResolutionResult(
            requested_seat=seat,
            resolved_seat=supervisor,
            fallback_tier=DoptorVacancyAlert.FallbackTier.IMMEDIATE_SUPERVISOR,
            vacancy_alert=alert,
        )

    def _find_occupied_supervisor(self, seat: DoptorSeat) -> DoptorSeat | None:
        visited = {seat.doptor_seat_id}
        cursor = seat.parent_seat
        hops = 0
        while cursor and hops < self.MAX_SUPERVISOR_HOPS:
            if cursor.doptor_seat_id in visited:
                break
            visited.add(cursor.doptor_seat_id)
            if cursor.is_occupied:
                return cursor
            cursor = (
                DoptorSeat.objects.select_related("office", "parent_seat__office")
                .filter(pk=cursor.parent_seat_id)
                .first()
                if cursor.parent_seat_id
                else None
            )
            hops += 1
        return None

    def _create_vacancy_alert(
        self,
        *,
        vacant_seat: DoptorSeat,
        routed_to_seat: DoptorSeat | None,
        complaint_id,
        fallback_tier: str,
        fire_hr_alert: bool,
    ) -> DoptorVacancyAlert:
        payload = {
            "vacant_seat_id": vacant_seat.doptor_seat_id,
            "vacant_designation": vacant_seat.designation_en,
            "office_id": vacant_seat.office.doptor_office_id,
            "routed_to_seat_id": routed_to_seat.doptor_seat_id if routed_to_seat else None,
            "doptor_hr_email": vacant_seat.doptor_hr_email,
            "complaint_id": str(complaint_id) if complaint_id else None,
        }
        alert = DoptorVacancyAlert.objects.create(
            vacant_seat=vacant_seat,
            routed_to_seat=routed_to_seat,
            complaint_id=complaint_id,
            fallback_tier=fallback_tier,
            hr_dispatch_status=(
                DoptorVacancyAlert.DispatchStatus.SENT
                if fire_hr_alert
                else DoptorVacancyAlert.DispatchStatus.PENDING
            ),
            payload=payload,
        )

        AuditLog.objects.create(
            complaint_id=complaint_id,
            actor_id="SYSTEM-SEAT-ROUTER",
            actor_seat_id=routed_to_seat.doptor_seat_id if routed_to_seat else "",
            actor_role="SYSTEM",
            action="VACANT_SEAT_SUPERVISOR_FALLBACK",
            entity_type="DoptorVacancyAlert",
            entity_id=str(alert.alert_id),
            payload=payload,
        )

        if fire_hr_alert:
            from apps.esb.tasks import dispatch_doptor_hr_vacancy_alert

            try:
                dispatch_doptor_hr_vacancy_alert.delay(str(alert.alert_id))
            except Exception as exc:
                logger.warning('Deferred Doptor HR alert dispatch for %s: %s', alert.alert_id, exc)

        return alert

    @transaction.atomic
    def assign_complaint_to_seat(
        self,
        *,
        complaint: Complaint,
        target_seat_id: str,
        due_at: datetime | None = None,
        fire_hr_alert: bool = True,
    ) -> tuple[TicketAssignment, SeatResolutionResult]:
        resolution = self.resolve_seat(
            target_seat_id=target_seat_id,
            complaint_id=complaint.complaint_id,
            fire_hr_alert=fire_hr_alert,
        )
        resolved = resolution.resolved_seat

        TicketAssignment.objects.filter(
            complaint=complaint,
            role_level=resolved.role_level,
            is_active=True,
        ).update(is_active=False)

        assignment = TicketAssignment.objects.create(
            complaint=complaint,
            doptor_office_id=resolved.office.doptor_office_id,
            doptor_seat_id=resolved.doptor_seat_id,
            assigned_officer_id=resolved.incumbent_officer_id,
            role_level=resolved.role_level,
            due_at=due_at or complaint.sla_deadline_at,
            is_active=True,
        )

        if complaint.status in (
            Complaint.ComplaintStatus.SUBMITTED,
            Complaint.ComplaintStatus.TRIAGED,
        ):
            complaint.status = Complaint.ComplaintStatus.ASSIGNED
            complaint.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            complaint=complaint,
            actor_id="SYSTEM-SEAT-ROUTER",
            actor_seat_id=resolved.doptor_seat_id,
            actor_role=resolved.role_level,
            action="TICKET_ROUTED_TO_SEAT",
            entity_type="TicketAssignment",
            entity_id=str(assignment.assignment_id),
            payload={
                "requested_seat_id": target_seat_id,
                "resolved_seat_id": resolved.doptor_seat_id,
                "fallback_tier": resolution.fallback_tier,
                "doptor_office_id": resolved.office.doptor_office_id,
            },
        )
        return assignment, resolution
