from django.contrib import admin, messages
from django.contrib.gis.admin import GISModelAdmin

from apps.complaints.models import AuditLog, Complaint, ResolutionReport, TicketAssignment


class TicketAssignmentInline(admin.TabularInline):
    model = TicketAssignment
    extra = 0
    readonly_fields = ("assignment_id", "assigned_at")
    fields = (
        "doptor_office_id",
        "doptor_seat_id",
        "assigned_officer_id",
        "role_level",
        "due_at",
        "is_active",
        "assigned_at",
    )


class ResolutionReportInline(admin.StackedInline):
    model = ResolutionReport
    extra = 0
    readonly_fields = ("report_id", "submitted_at")


@admin.register(Complaint)
class ComplaintAdmin(GISModelAdmin):
    gis_widget_kwargs = {
        "attrs": {
            "default_lon": 90.4125,
            "default_lat": 23.8103,
            "default_zoom": 11,
        }
    }
    list_display = (
        "tracking_code",
        "urgency_tier",
        "status",
        "ai_category_code",
        "admin_geo_code",
        "transfer_count",
        "escalation_level",
        "is_arbitration_locked",
        "sla_deadline_at",
        "created_at",
    )
    list_filter = (
        "status",
        "urgency_tier",
        "is_anonymous",
        "is_arbitration_locked",
        "hold_reason_code",
        "escalation_level",
    )
    search_fields = (
        "tracking_code",
        "complaint_id",
        "citizen_uct_hash",
        "admin_geo_code",
        "h3_hex_index",
        "ai_category_code",
        "raw_text_en",
        "raw_text_bn",
    )
    readonly_fields = ("complaint_id", "created_at", "updated_at")
    raw_id_fields = ("parent_case", "master_cluster")
    inlines = [TicketAssignmentInline, ResolutionReportInline]


@admin.register(TicketAssignment)
class TicketAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "complaint",
        "doptor_office_id",
        "doptor_seat_id",
        "role_level",
        "assigned_officer_id",
        "due_at",
        "is_active",
    )
    list_filter = ("role_level", "is_active")
    search_fields = (
        "complaint__tracking_code",
        "doptor_office_id",
        "doptor_seat_id",
        "assigned_officer_id",
    )
    raw_id_fields = ("complaint",)


@admin.register(ResolutionReport)
class ResolutionReportAdmin(admin.ModelAdmin):
    list_display = (
        "report_id",
        "complaint",
        "submitted_by_seat",
        "gps_verified_dist_m",
        "citizen_verdict",
        "submitted_at",
    )
    list_filter = ("citizen_verdict",)
    search_fields = ("complaint__tracking_code", "submitted_by_seat", "work_summary")
    raw_id_fields = ("complaint",)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "sequence_no",
        "action",
        "complaint",
        "actor_id",
        "actor_seat_id",
        "short_hash",
        "created_at",
    )
    list_filter = ("action", "entity_type", "actor_role")
    search_fields = ("complaint__tracking_code", "actor_id", "actor_seat_id", "current_hash")
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    actions = ["verify_hash_chain_action"]

    @admin.display(description="SHA-256 Hash")
    def short_hash(self, obj: AuditLog) -> str:
        return f"{obj.current_hash[:16]}..."

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Verify SHA-256 Audit Ledger Chain Integrity")
    def verify_hash_chain_action(self, request, queryset):
        is_valid, checked, broken_id = AuditLog.verify_chain()
        if is_valid:
            self.message_user(
                request,
                f"Audit chain verified intact across all {checked} ledger entries.",
                level=messages.SUCCESS,
            )
        else:
            self.message_user(
                request,
                f"TAMPERING DETECTED at log_id={broken_id} (checked {checked} entries).",
                level=messages.ERROR,
            )
