from django.contrib import admin

from apps.ai_triage.models import (
    MasterIncidentSubscription,
    SubTicketDependency,
    TriageRun,
)


@admin.register(TriageRun)
class TriageRunAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "primary_ministry_code",
        "primary_agency_code",
        "confidence_score",
        "routing_decision",
        "gro_one_click_reassign_flag",
        "vlm_evidence_valid",
        "created_at",
    )
    list_filter = (
        "routing_decision",
        "gro_one_click_reassign_flag",
        "vlm_evidence_valid",
        "primary_agency_code",
    )
    search_fields = ("complaint__tracking_code", "primary_agency_code", "asr_transcript_bn")
    raw_id_fields = ("complaint",)


@admin.register(SubTicketDependency)
class SubTicketDependencyAdmin(admin.ModelAdmin):
    list_display = (
        "parent_case",
        "sequence_order",
        "prerequisite_ticket",
        "dependent_ticket",
        "is_satisfied",
        "satisfied_at",
    )
    list_filter = ("is_satisfied",)
    raw_id_fields = ("parent_case", "prerequisite_ticket", "dependent_ticket")


@admin.register(MasterIncidentSubscription)
class MasterIncidentSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("master_complaint", "citizen_uct_hash", "notify_channel", "subscribed_at")
    list_filter = ("notify_channel",)
    search_fields = ("master_complaint__tracking_code", "citizen_uct_hash")
    raw_id_fields = ("master_complaint", "duplicate_complaint")
