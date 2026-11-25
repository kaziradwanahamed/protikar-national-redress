"""
Tier 3 National ESB: Zero-IT Built-In Workspace for Union Parishads and Rural Field Offices.
Requires zero external legacy software—officers manage assigned seat tickets directly via API/HTMX.
"""

from __future__ import annotations

from apps.complaints.models import AuditLog, Complaint, TicketAssignment


class Tier3ZeroITWorkspaceService:
    """Lightweight inbox and field-action service for Union Parishads & rural field seats."""

    @staticmethod
    def list_seat_inbox(doptor_seat_id: str) -> list[dict]:
        assignments = (
            TicketAssignment.objects.select_related("complaint")
            .filter(doptor_seat_id=doptor_seat_id, is_active=True)
            .order_by("due_at")
        )
        return [
            {
                "assignment_id": str(a.assignment_id),
                "complaint_id": str(a.complaint.complaint_id),
                "tracking_code": a.complaint.tracking_code,
                "urgency_tier": a.complaint.urgency_tier,
                "status": a.complaint.status,
                "summary": a.complaint.raw_text_bn or a.complaint.raw_text_en,
                "due_at": a.due_at.isoformat() if a.due_at else None,
            }
            for a in assignments
        ]

    @staticmethod
    def post_rural_field_update(
        *, complaint: Complaint, seat_id: str, actor_id: str, update_note: str
    ) -> dict:
        if complaint.status == Complaint.ComplaintStatus.ROUTED:
            complaint.status = Complaint.ComplaintStatus.IN_PROGRESS
            complaint.save(update_fields=["status", "updated_at"])

        log = AuditLog.objects.create(
            complaint=complaint,
            actor_id=actor_id,
            actor_seat_id=seat_id,
            actor_role="FIELD_WORKER",
            action="TIER3_RURAL_WORKSPACE_UPDATE",
            entity_type="Complaint",
            entity_id=str(complaint.complaint_id),
            payload={"update_note": update_note.strip()},
        )
        return {
            "tracking_code": complaint.tracking_code,
            "status": complaint.status,
            "audit_log_id": str(log.log_id),
        }
