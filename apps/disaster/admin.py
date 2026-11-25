from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.disaster.models import CrisisZone, EmergencyCommandDispatch


@admin.register(CrisisZone)
class CrisisZoneAdmin(GISModelAdmin):
    list_display = (
        "crisis_code",
        "name_en",
        "disaster_type",
        "trigger_source",
        "frozen_ticket_count",
        "is_active",
        "activated_at",
    )
    list_filter = ("disaster_type", "trigger_source", "is_active")
    search_fields = ("crisis_code", "name_en", "name_bn")


@admin.register(EmergencyCommandDispatch)
class EmergencyCommandDispatchAdmin(GISModelAdmin):
    list_display = (
        "dispatch_id",
        "h3_res8_index",
        "citizen_phone",
        "status",
        "kafka_topic",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("raw_message", "h3_res8_index", "citizen_phone")
