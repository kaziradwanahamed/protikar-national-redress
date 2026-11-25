"""
Compound Complaint Splitter with Engineering Dependency Sequencing.

Detects multi-agency complaints (e.g., burst WASA pipe + snapped DESCO pole + damaged road),
retains 1 Parent Case ID, spawns linked Child Sub-Tickets, and enforces sequential
dependencies (e.g., DESCO power safety -> WASA underground pipe -> City Corp/RHD road paving).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.ai_triage.models import SubTicketDependency
from apps.ai_triage.services.classifier import LabelPrediction
from apps.ai_triage.services.geo_resolver import JurisdictionResolution, PostGISJurisdictionResolver
from apps.complaints.models import AuditLog, Complaint
from apps.workflow.services.sla_service import TieredSLAService


@dataclass(frozen=True)
class CompoundSplitResult:
    parent_case: Complaint
    child_tickets: list[Complaint]
    dependencies: list[SubTicketDependency]


class CompoundComplaintSplitter:
    """Splits multi-agency grievances into ordered, dependency-linked Child Sub-Tickets."""

    @classmethod
    @transaction.atomic
    def split(
        cls,
        *,
        parent_complaint: Complaint,
        predictions: list[LabelPrediction],
        jurisdiction: JurisdictionResolution,
        actor_id: str = "SYSTEM-AI-SPLITTER",
    ) -> CompoundSplitResult:
        # Deduplicate by agency_code and order by engineering_phase (1=Power, 2=Underground, 3=Road)
        seen_agencies: set[str] = set()
        ordered_preds: list[LabelPrediction] = []
        for pred in sorted(predictions, key=lambda p: (p.engineering_phase, -p.confidence)):
            if pred.agency_code not in seen_agencies:
                seen_agencies.add(pred.agency_code)
                ordered_preds.append(pred)

        child_tickets: list[Complaint] = []
        phase_groups: dict[int, list[Complaint]] = {}

        for pred in ordered_preds:
            child = Complaint.objects.create(
                parent_case=parent_complaint,
                citizen_uct_hash=parent_complaint.citizen_uct_hash,
                is_anonymous=parent_complaint.is_anonymous,
                raw_text_bn=parent_complaint.raw_text_bn,
                raw_text_en=f"[{pred.agency_code} Sub-Ticket] {parent_complaint.raw_text_en}".strip(),
                voice_audio_url=parent_complaint.voice_audio_url,
                ai_category_code=pred.category_code,
                ai_confidence=pred.confidence,
                urgency_tier=pred.urgency_tier,
                geo_point=parent_complaint.geo_point or jurisdiction.resolved_point,
                admin_geo_code=parent_complaint.admin_geo_code or jurisdiction.bbs_geo_code,
                h3_hex_index=parent_complaint.h3_hex_index,
                status=Complaint.ComplaintStatus.SUBMITTED,
            )
            child_tickets.append(child)
            phase_groups.setdefault(pred.engineering_phase, []).append(child)

        # Build dependency DAG across consecutive engineering phases
        sorted_phases = sorted(phase_groups.keys())
        dependencies: list[SubTicketDependency] = []
        seq = 1
        for idx in range(len(sorted_phases) - 1):
            prereq_phase = sorted_phases[idx]
            dep_phase = sorted_phases[idx + 1]
            for prereq_ticket in phase_groups[prereq_phase]:
                for dep_ticket in phase_groups[dep_phase]:
                    dep = SubTicketDependency.objects.create(
                        parent_case=parent_complaint,
                        prerequisite_ticket=prereq_ticket,
                        dependent_ticket=dep_ticket,
                        sequence_order=seq,
                        reason=(
                            f"Phase-{prereq_phase} ({prereq_ticket.ai_category_code}) must finish "
                            f"before Phase-{dep_phase} ({dep_ticket.ai_category_code}) starts."
                        ),
                    )
                    dependencies.append(dep)
                    seq += 1

        # Route Phase-1 (unblocked) child tickets immediately; hold later phases until prerequisites finish
        first_phase = sorted_phases[0]
        pred_by_cat = {p.category_code: p for p in ordered_preds}
        for child in phase_groups[first_phase]:
            pred = pred_by_cat[child.ai_category_code]
            seat_id = PostGISJurisdictionResolver.pick_seat_for_zone_type(
                jurisdiction, pred.zone_type
            )
            if seat_id:
                TieredSLAService.route_complaint(
                    complaint=child, target_seat_id=seat_id, actor_id=actor_id
                )

        parent_complaint.status = Complaint.ComplaintStatus.ROUTED
        parent_complaint.save(update_fields=["status", "updated_at"])

        AuditLog.objects.create(
            complaint=parent_complaint,
            actor_id=actor_id,
            actor_role="SYSTEM",
            action="COMPOUND_COMPLAINT_SPLIT",
            entity_type="Complaint",
            entity_id=str(parent_complaint.complaint_id),
            payload={
                "child_tracking_codes": [c.tracking_code for c in child_tickets],
                "dependency_count": len(dependencies),
            },
        )
        return CompoundSplitResult(
            parent_case=parent_complaint,
            child_tickets=child_tickets,
            dependencies=dependencies,
        )

    @classmethod
    @transaction.atomic
    def release_dependent_subtickets(cls, completed_ticket: Complaint) -> list[Complaint]:
        """Mark prerequisite edges satisfied and auto-route any newly unblocked dependent sub-tickets."""
        now = timezone.now()
        edges = list(
            SubTicketDependency.objects.select_related("dependent_ticket").filter(
                prerequisite_ticket=completed_ticket, is_satisfied=False
            )
        )
        released: list[Complaint] = []
        for edge in edges:
            edge.is_satisfied = True
            edge.satisfied_at = now
            edge.save(update_fields=["is_satisfied", "satisfied_at"])

            dependent = edge.dependent_ticket
            still_blocked = SubTicketDependency.objects.filter(
                dependent_ticket=dependent, is_satisfied=False
            ).exists()
            if not still_blocked and dependent.status == Complaint.ComplaintStatus.SUBMITTED:
                jurisdiction = PostGISJurisdictionResolver.resolve(
                    geo_point=dependent.geo_point,
                    text_bn=dependent.raw_text_bn,
                    text_en=dependent.raw_text_en,
                )
                seat_id = PostGISJurisdictionResolver.pick_seat_for_zone_type(
                    jurisdiction, ""
                )
                if seat_id:
                    TieredSLAService.route_complaint(
                        complaint=dependent,
                        target_seat_id=seat_id,
                        actor_id="SYSTEM-DEPENDENCY-RELEASE",
                    )
                released.append(dependent)
        return released
