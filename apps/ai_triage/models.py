import uuid
from django.db import models

from apps.complaints.models import Complaint


class TriageRun(models.Model):
    """Stores multimodal ASR/VLM pre-processing, multi-label classification, and routing output."""

    class RoutingDecision(models.TextChoices):
        AUTO_ROUTED = "AUTO_ROUTED", "Auto-Routed Immediately (>=85%)"
        GRO_REASSIGN_FLAGGED = "GRO_REASSIGN_FLAGGED", "Routed with 1-Click GRO Reassign Flag (60-84%)"
        CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED", "Clarifying Questions Returned (<60%)"
        COMPOUND_SPLIT = "COMPOUND_SPLIT", "Split into Parent + Dependent Child Sub-Tickets"
        MERGED_DUPLICATE = "MERGED_DUPLICATE", "Merged into Spatial Master Incident (<=200m)"

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="triage_runs"
    )
    asr_transcript_bn = models.TextField(blank=True)
    asr_transcript_en = models.TextField(blank=True)
    detected_dialect = models.CharField(max_length=32, blank=True)

    vlm_evidence_valid = models.BooleanField(default=True)
    vlm_evidence_labels = models.JSONField(default=list, blank=True)
    ocr_extracted_refs = models.JSONField(default=dict, blank=True)

    primary_ministry_code = models.CharField(max_length=64, blank=True, db_index=True)
    primary_agency_code = models.CharField(max_length=64, blank=True, db_index=True)
    predicted_labels = models.JSONField(default=list, blank=True)
    confidence_score = models.FloatField(default=0.0)

    routing_decision = models.CharField(
        max_length=32, choices=RoutingDecision.choices, db_index=True
    )
    gro_one_click_reassign_flag = models.BooleanField(default=False, db_index=True)
    clarifying_questions = models.JSONField(default=list, blank=True)

    extracted_geo_entities = models.JSONField(default=list, blank=True)
    resolved_zone_codes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_triage_run"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"TriageRun({self.complaint.tracking_code} | {self.routing_decision} | {self.confidence_score:.2f})"


class SubTicketDependency(models.Model):
    """
    Dependency edge between child sub-tickets spawned from a Compound Complaint.
    Example: WASA burst-pipe repair must complete before City Corp road resurfacing starts.
    """

    dependency_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent_case = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="subticket_dependencies"
    )
    prerequisite_ticket = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="blocking_dependents"
    )
    dependent_ticket = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="blocked_by_prerequisites"
    )
    sequence_order = models.PositiveSmallIntegerField(default=1)
    reason = models.CharField(max_length=255)
    is_satisfied = models.BooleanField(default=False, db_index=True)
    satisfied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_triage_subticket_dependency"
        ordering = ["parent_case", "sequence_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["prerequisite_ticket", "dependent_ticket"],
                name="uq_subticket_dependency_edge",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.prerequisite_ticket.tracking_code} -> {self.dependent_ticket.tracking_code}"


class MasterIncidentSubscription(models.Model):
    """Subscribes unique citizens from spatially deduplicated complaints to live Master Incident updates."""

    class NotifyChannel(models.TextChoices):
        SMS = "SMS", "SMS Alert"
        PUSH = "PUSH", "Mobile Push Notification"
        WEB = "WEB", "Web Portal Live Feed"

    subscription_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    master_complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="cluster_subscriptions"
    )
    duplicate_complaint = models.ForeignKey(
        Complaint,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="master_subscription_links",
    )
    citizen_uct_hash = models.CharField(max_length=64, db_index=True)
    notify_channel = models.CharField(
        max_length=16, choices=NotifyChannel.choices, default=NotifyChannel.SMS
    )
    subscribed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_triage_master_incident_subscription"
        constraints = [
            models.UniqueConstraint(
                fields=["master_complaint", "citizen_uct_hash"],
                name="uq_master_incident_unique_citizen",
            ),
        ]

    def __str__(self) -> str:
        return f"Sub({self.master_complaint.tracking_code} <- {self.citizen_uct_hash[:10]}...)"
