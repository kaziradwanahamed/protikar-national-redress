from rest_framework import serializers

from apps.ai_triage.models import (
    MasterIncidentSubscription,
    SubTicketDependency,
    TriageRun,
)


class TriggerTriageSerializer(serializers.Serializer):
    photo_urls = serializers.ListField(
        child=serializers.URLField(max_length=1024), required=False, default=list
    )
    run_async = serializers.BooleanField(default=False)


class TriageRunSerializer(serializers.ModelSerializer):
    tracking_code = serializers.CharField(source="complaint.tracking_code", read_only=True)

    class Meta:
        model = TriageRun
        fields = (
            "run_id",
            "tracking_code",
            "asr_transcript_bn",
            "asr_transcript_en",
            "detected_dialect",
            "vlm_evidence_valid",
            "vlm_evidence_labels",
            "ocr_extracted_refs",
            "primary_ministry_code",
            "primary_agency_code",
            "predicted_labels",
            "confidence_score",
            "routing_decision",
            "gro_one_click_reassign_flag",
            "clarifying_questions",
            "extracted_geo_entities",
            "resolved_zone_codes",
            "created_at",
        )


class SubTicketDependencySerializer(serializers.ModelSerializer):
    prerequisite_tracking_code = serializers.CharField(
        source="prerequisite_ticket.tracking_code", read_only=True
    )
    dependent_tracking_code = serializers.CharField(
        source="dependent_ticket.tracking_code", read_only=True
    )

    class Meta:
        model = SubTicketDependency
        fields = (
            "dependency_id",
            "prerequisite_tracking_code",
            "dependent_tracking_code",
            "sequence_order",
            "reason",
            "is_satisfied",
            "satisfied_at",
        )


class MasterIncidentSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterIncidentSubscription
        fields = (
            "subscription_id",
            "citizen_uct_hash",
            "notify_channel",
            "subscribed_at",
        )
