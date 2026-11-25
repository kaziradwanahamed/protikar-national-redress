from django.contrib import admin

from apps.esb.models import AgencyEndpoint, ESBDeliveryLog, OmnichannelIntakeRecord


@admin.register(AgencyEndpoint)
class AgencyEndpointAdmin(admin.ModelAdmin):
    list_display = ("agency_code", "agency_name", "tier", "polling_enabled", "last_synced_at", "is_active")
    list_filter = ("tier", "polling_enabled", "is_active")
    search_fields = ("agency_code", "agency_name")


@admin.register(ESBDeliveryLog)
class ESBDeliveryLogAdmin(admin.ModelAdmin):
    list_display = ("agency_code", "direction", "event_type", "status", "http_status", "created_at")
    list_filter = ("direction", "status", "agency_code")
    search_fields = ("agency_code", "idempotency_key", "event_type")


@admin.register(OmnichannelIntakeRecord)
class OmnichannelIntakeRecordAdmin(admin.ModelAdmin):
    list_display = ("channel", "sender_id", "byte_length", "crisis_fastlane_triggered", "created_at")
    list_filter = ("channel", "crisis_fastlane_triggered")
    search_fields = ("sender_id", "raw_payload")
