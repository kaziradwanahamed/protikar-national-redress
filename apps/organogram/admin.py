from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from apps.organogram.models import (
    DoptorOffice,
    DoptorSeat,
    DoptorVacancyAlert,
    ServiceAreaPolygon,
)


@admin.register(DoptorOffice)
class DoptorOfficeAdmin(admin.ModelAdmin):
    list_display = (
        "doptor_office_id",
        "office_code",
        "name_en",
        "office_layer",
        "ministry_code",
        "bbs_geo_code",
        "last_synced_at",
        "is_active",
    )
    list_filter = ("office_layer", "is_active")
    search_fields = ("doptor_office_id", "office_code", "name_en", "name_bn", "bbs_geo_code")
    raw_id_fields = ("parent_office",)


@admin.register(DoptorSeat)
class DoptorSeatAdmin(admin.ModelAdmin):
    list_display = (
        "doptor_seat_id",
        "designation_en",
        "office",
        "role_level",
        "incumbent_name_en",
        "is_vacant",
        "additional_charge_seat",
        "parent_seat",
        "is_active",
    )
    list_filter = ("role_level", "is_vacant", "is_active", "office__office_layer")
    search_fields = (
        "doptor_seat_id",
        "designation_en",
        "designation_bn",
        "incumbent_officer_id",
        "incumbent_name_en",
    )
    raw_id_fields = ("office", "parent_seat", "additional_charge_seat")


@admin.register(DoptorVacancyAlert)
class DoptorVacancyAlertAdmin(admin.ModelAdmin):
    list_display = (
        "alert_id",
        "vacant_seat",
        "routed_to_seat",
        "fallback_tier",
        "hr_dispatch_status",
        "created_at",
    )
    list_filter = ("fallback_tier", "hr_dispatch_status")
    search_fields = ("vacant_seat__doptor_seat_id", "routed_to_seat__doptor_seat_id")
    readonly_fields = ("alert_id", "created_at")


@admin.register(ServiceAreaPolygon)
class ServiceAreaPolygonAdmin(GISModelAdmin):
    gis_widget_kwargs = {
        "attrs": {
            "default_lon": 90.4125,
            "default_lat": 23.8103,
            "default_zoom": 10,
        }
    }
    list_display = (
        "zone_code",
        "name_en",
        "zone_type",
        "bbs_geo_code",
        "primary_office",
        "default_gro_seat",
        "is_active",
    )
    list_filter = ("zone_type", "is_active")
    search_fields = ("zone_code", "name_en", "name_bn", "bbs_geo_code")
    raw_id_fields = ("parent_area", "primary_office", "default_gro_seat")
