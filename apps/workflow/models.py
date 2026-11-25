import uuid
from django.db import models
from django.utils import timezone

from apps.complaints.models import Complaint


class WorkflowTracker(models.Model):
    """Tracks statutory SLA clock, pause intervals, acknowledgement, and verification deadlines."""

    tracker_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.OneToOneField(
        Complaint, on_delete=models.CASCADE, related_name="workflow_tracker"
    )
    sla_started_at = models.DateTimeField(default=timezone.now, db_index=True)
    sla_total_seconds = models.PositiveIntegerField(
        help_text="Total statutory SLA duration in seconds (P1=4h, P2=48h, P3=7-15d, P4=30d)."
    )
    sla_paused_at = models.DateTimeField(null=True, blank=True, db_index=True)
    sla_accumulated_pause_seconds = models.PositiveIntegerField(default=0)

    acknowledged_at = models.DateTimeField(null=True, blank=True, db_index=True)
    auto_acknowledged = models.BooleanField(default=False)

    field_worker_sub_deadline_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="70% SLA sub-deadline assigned to the field worker by Unit Supervisor.",
    )
    yellow_warning_sent_at = models.DateTimeField(null=True, blank=True)

    pending_citizen_verify_at = models.DateTimeField(null=True, blank=True)
    citizen_verify_deadline_at = models.DateTimeField(
        null=True, blank=True, db_index=True, help_text="72-hour citizen verification window."
    )
    auto_closed_audit_flag = models.BooleanField(default=False, db_index=True)

    officer_rebuttal_deadline_at = models.DateTimeField(
        null=True, blank=True, db_index=True, help_text="48-hour Right of Reply window."
    )
    p1_accepted_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp when P1 emergency ticket was accepted (Accept-First, Dispute-Later).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_tracker"
        indexes = [
            models.Index(
                fields=["citizen_verify_deadline_at", "auto_closed_audit_flag"],
                name="idx_wf_verify_deadline",
            ),
            models.Index(
                fields=["acknowledged_at", "sla_started_at"],
                name="idx_wf_ack_check",
            ),
        ]

    @property
    def is_sla_paused(self) -> bool:
        return self.sla_paused_at is not None

    def elapsed_active_seconds(self, now=None) -> float:
        now = now or timezone.now()
        effective_now = self.sla_paused_at if self.sla_paused_at else now
        raw_elapsed = max(0.0, (effective_now - self.sla_started_at).total_seconds())
        return max(0.0, raw_elapsed - self.sla_accumulated_pause_seconds)

    def elapsed_ratio(self, now=None) -> float:
        if self.sla_total_seconds <= 0:
            return 1.0
        return self.elapsed_active_seconds(now=now) / float(self.sla_total_seconds)

    def __str__(self) -> str:
        return f"WorkflowTracker({self.complaint.tracking_code})"


class CapitalMilestone(models.Model):
    """
    Public Capital Milestone Tracker activated when a ticket enters ON_HOLD_PROCUREMENT
    with a verified e-GP Tender ID or D-Nothi Reference.
    """

    class Stage(models.TextChoices):
        BUDGET_APPROVED = "BUDGET_APPROVED", "1. Budget Approved"
        EGP_TENDER_FLOATED = "EGP_TENDER_FLOATED", "2. e-GP Tender Floated"
        WORK_ORDER_ISSUED = "WORK_ORDER_ISSUED", "3. Work Order Issued"
        EXECUTION = "EXECUTION", "4. Physical Execution"

    class ReferenceType(models.TextChoices):
        EGP_TENDER = "EGP_TENDER", "e-GP Tender ID"
        D_NOTHI = "D_NOTHI", "D-Nothi Reference"

    milestone_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="capital_milestones"
    )
    stage = models.CharField(max_length=24, choices=Stage.choices, db_index=True)
    stage_order = models.PositiveSmallIntegerField(default=1)
    reference_type = models.CharField(max_length=16, choices=ReferenceType.choices)
    reference_id = models.CharField(max_length=128, db_index=True)
    notes = models.TextField(blank=True)
    is_completed = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    updated_by_seat = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "workflow_capital_milestone"
        ordering = ["complaint", "stage_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["complaint", "stage"], name="uq_capital_milestone_per_stage"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.complaint.tracking_code} | {self.stage} ({'Done' if self.is_completed else 'Pending'})"


class ArbitrationCase(models.Model):
    """
    Jurisdiction Arbitration record created when transfer_count reaches 2 (ARBITRATION_LOCKED).
    Decision SLA: 24 hours (2 hours for P1).
    """

    class JurisdictionScope(models.TextChoices):
        UPAZILA_UNO = "UPAZILA_UNO", "Upazila Nirbahi Officer (UNO — Intra-Upazila)"
        DISTRICT_DC = "DISTRICT_DC", "Deputy Commissioner (DC — Intra-District)"
        DIVISIONAL_CABINET = (
            "DIVISIONAL_CABINET",
            "Divisional Commissioner / Cabinet Cell (Inter-Agency)",
        )

    arbitration_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.OneToOneField(
        Complaint, on_delete=models.CASCADE, related_name="arbitration_case"
    )
    jurisdiction_scope = models.CharField(
        max_length=24, choices=JurisdictionScope.choices, db_index=True
    )
    arbitrator_seat_id = models.CharField(max_length=64, db_index=True)
    decision_sla_deadline_at = models.DateTimeField(db_index=True)
    disputing_seats = models.JSONField(default=list, blank=True)
    ruling_assigned_seat_id = models.CharField(max_length=64, blank=True)
    ruling_notes = models.TextField(blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workflow_arbitration_case"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Arbitration({self.complaint.tracking_code} -> {self.jurisdiction_scope})"


class EscalationEvent(models.Model):
    """Records 80% Yellow Warnings, 100% 4-Tier SLA Escalations, and APA scorecard impacts."""

    class EventType(models.TextChoices):
        YELLOW_WARNING_80 = "YELLOW_WARNING_80", "80% SLA Yellow Warning to Supervisor"
        SLA_BREACH_100 = "SLA_BREACH_100", "100% SLA Breach Auto-Escalation"
        CITIZEN_REJECTION = "CITIZEN_REJECTION", "Citizen Rejection Auto-Escalation"

    class EscalationTier(models.IntegerChoices):
        TIER_1_UNIT = 1, "Tier 1 — Field / Unit Supervisor / GRO"
        TIER_2_DISTRICT = 2, "Tier 2 — District DC / Executive Engineer"
        TIER_3_DIVISIONAL = 3, "Tier 3 — Divisional Commissioner / Director General"
        TIER_4_MINISTRY = 4, "Tier 4 — Ministry Secretary / Cabinet Cell"

    event_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="escalation_events"
    )
    event_type = models.CharField(max_length=24, choices=EventType.choices, db_index=True)
    escalation_tier = models.PositiveSmallIntegerField(
        choices=EscalationTier.choices, db_index=True
    )
    from_seat_id = models.CharField(max_length=64, blank=True)
    to_seat_id = models.CharField(max_length=64, blank=True, db_index=True)
    apa_scorecard_impact = models.FloatField(
        default=0.0,
        help_text="Annual Performance Agreement (APA) penalty delta (0.0 for warnings/cleared).",
    )
    ddcc_flagged = models.BooleanField(default=False, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "workflow_escalation_event"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.complaint.tracking_code} | {self.event_type} (Tier {self.escalation_tier})"


class DDCCAgendaItem(models.Model):
    """Monthly District Development Coordination Committee (DDCC) agenda item for Level-3 breaches."""

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled for Monthly DDCC"
        REVIEWED = "REVIEWED", "Reviewed in DDCC Session"
        RESOLVED = "RESOLVED", "Resolved Post-DDCC Directive"

    agenda_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="ddcc_agenda_items"
    )
    escalation_event = models.ForeignKey(
        EscalationEvent, on_delete=models.CASCADE, related_name="ddcc_items"
    )
    district_bbs_code = models.CharField(max_length=16, db_index=True)
    agenda_month = models.CharField(max_length=7, db_index=True, help_text="YYYY-MM format.")
    summary = models.TextField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.SCHEDULED, db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "workflow_ddcc_agenda_item"
        ordering = ["-agenda_month", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["complaint", "agenda_month"], name="uq_ddcc_complaint_month"
            ),
        ]

    def __str__(self) -> str:
        return f"DDCC {self.agenda_month} | {self.complaint.tracking_code}"
