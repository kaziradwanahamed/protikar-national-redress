from rest_framework import serializers

from apps.complaints.models import ResolutionReport
from apps.workflow.models import (
    ArbitrationCase,
    CapitalMilestone,
    DDCCAgendaItem,
    EscalationEvent,
    WorkflowTracker,
)


class RouteComplaintSerializer(serializers.Serializer):
    target_seat_id = serializers.CharField(max_length=64)
    p3_days = serializers.IntegerField(default=10, min_value=7, max_value=15)


class AssignFieldWorkerSerializer(serializers.Serializer):
    field_worker_seat_id = serializers.CharField(max_length=64)


class SubmitResolutionSerializer(serializers.Serializer):
    submitted_by_seat = serializers.CharField(max_length=64)
    supervisor_signoff_seat = serializers.CharField(max_length=64)
    work_summary = serializers.CharField(min_length=10, max_length=4000)
    after_photo_urls = serializers.ListField(
        child=serializers.URLField(max_length=1024), allow_empty=False
    )
    after_lon = serializers.FloatField(min_value=-180.0, max_value=180.0)
    after_lat = serializers.FloatField(min_value=-90.0, max_value=90.0)


class CitizenVerdictSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(
        choices=[
            ResolutionReport.CitizenVerdict.ACCEPTED,
            ResolutionReport.CitizenVerdict.REJECTED,
        ]
    )
    feedback = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    evidence_urls = serializers.ListField(
        child=serializers.URLField(max_length=1024), required=False, default=list
    )


class TransferRequestSerializer(serializers.Serializer):
    target_seat_id = serializers.CharField(max_length=64)
    reason = serializers.CharField(min_length=10, max_length=1000)


class ProcurementHoldSerializer(serializers.Serializer):
    reference_type = serializers.ChoiceField(choices=CapitalMilestone.ReferenceType.choices)
    reference_id = serializers.CharField(min_length=4, max_length=128)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class AdvanceMilestoneSerializer(serializers.Serializer):
    stage = serializers.ChoiceField(choices=CapitalMilestone.Stage.choices)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class OfficerContestSerializer(serializers.Serializer):
    rebuttal_url = serializers.URLField(max_length=1024)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class UnfoundedClearSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=10, max_length=2000)
    strike_penalty = serializers.FloatField(default=25.0, min_value=5.0, max_value=100.0)


class WorkflowTrackerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowTracker
        fields = (
            "tracker_id",
            "sla_started_at",
            "sla_total_seconds",
            "sla_paused_at",
            "sla_accumulated_pause_seconds",
            "acknowledged_at",
            "auto_acknowledged",
            "field_worker_sub_deadline_at",
            "yellow_warning_sent_at",
            "pending_citizen_verify_at",
            "citizen_verify_deadline_at",
            "auto_closed_audit_flag",
            "officer_rebuttal_deadline_at",
            "p1_accepted_at",
        )


class CapitalMilestoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = CapitalMilestone
        fields = (
            "milestone_id",
            "stage",
            "stage_order",
            "reference_type",
            "reference_id",
            "notes",
            "is_completed",
            "completed_at",
            "updated_by_seat",
        )


class ArbitrationCaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArbitrationCase
        fields = (
            "arbitration_id",
            "jurisdiction_scope",
            "arbitrator_seat_id",
            "decision_sla_deadline_at",
            "disputing_seats",
            "ruling_assigned_seat_id",
            "ruling_notes",
            "resolved_at",
        )


class EscalationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = EscalationEvent
        fields = (
            "event_id",
            "event_type",
            "escalation_tier",
            "from_seat_id",
            "to_seat_id",
            "apa_scorecard_impact",
            "ddcc_flagged",
            "notes",
            "created_at",
        )


class DDCCAgendaItemSerializer(serializers.ModelSerializer):
    tracking_code = serializers.CharField(source="complaint.tracking_code", read_only=True)

    class Meta:
        model = DDCCAgendaItem
        fields = (
            "agenda_id",
            "tracking_code",
            "district_bbs_code",
            "agenda_month",
            "summary",
            "status",
            "created_at",
        )
