from django.contrib import admin

from apps.workflow.models import (
    ArbitrationCase,
    CapitalMilestone,
    DDCCAgendaItem,
    EscalationEvent,
    WorkflowTracker,
)


@admin.register(WorkflowTracker)
class WorkflowTrackerAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "sla_started_at",
        "sla_total_seconds",
        "acknowledged_at",
        "yellow_warning_sent_at",
        "citizen_verify_deadline_at",
        "auto_closed_audit_flag",
    )
    list_filter = ("auto_acknowledged", "auto_closed_audit_flag")
    search_fields = ("complaint__tracking_code",)
    raw_id_fields = ("complaint",)


@admin.register(CapitalMilestone)
class CapitalMilestoneAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "stage",
        "reference_type",
        "reference_id",
        "is_completed",
        "completed_at",
    )
    list_filter = ("stage", "reference_type", "is_completed")
    search_fields = ("complaint__tracking_code", "reference_id")
    raw_id_fields = ("complaint",)


@admin.register(ArbitrationCase)
class ArbitrationCaseAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "jurisdiction_scope",
        "arbitrator_seat_id",
        "decision_sla_deadline_at",
        "resolved_at",
    )
    list_filter = ("jurisdiction_scope",)
    search_fields = ("complaint__tracking_code", "arbitrator_seat_id")
    raw_id_fields = ("complaint",)


@admin.register(EscalationEvent)
class EscalationEventAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "event_type",
        "escalation_tier",
        "from_seat_id",
        "to_seat_id",
        "apa_scorecard_impact",
        "ddcc_flagged",
        "created_at",
    )
    list_filter = ("event_type", "escalation_tier", "ddcc_flagged")
    search_fields = ("complaint__tracking_code", "from_seat_id", "to_seat_id")
    raw_id_fields = ("complaint",)


@admin.register(DDCCAgendaItem)
class DDCCAgendaItemAdmin(admin.ModelAdmin):
    list_display = ("agenda_month", "district_bbs_code", "complaint", "status", "created_at")
    list_filter = ("agenda_month", "status")
    search_fields = ("complaint__tracking_code", "district_bbs_code")
    raw_id_fields = ("complaint", "escalation_event")
