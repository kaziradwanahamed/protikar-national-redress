from rest_framework import serializers

from apps.organogram.models import DoptorOffice, DoptorSeat, DoptorVacancyAlert


class DoptorSSOLoginSerializer(serializers.Serializer):
    doptor_token = serializers.CharField(max_length=512)


class DoptorOfficeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DoptorOffice
        fields = (
            "office_id",
            "doptor_office_id",
            "office_code",
            "name_en",
            "name_bn",
            "office_layer",
            "ministry_code",
            "directorate_code",
            "division_code",
            "district_code",
            "upazila_code",
            "bbs_geo_code",
            "last_synced_at",
            "is_active",
        )


class DoptorSeatSerializer(serializers.ModelSerializer):
    office_code = serializers.CharField(source="office.office_code", read_only=True)
    additional_charge_seat_id = serializers.CharField(read_only=True)
    immediate_supervisor_seat_id = serializers.CharField(read_only=True)
    is_occupied = serializers.BooleanField(read_only=True)

    class Meta:
        model = DoptorSeat
        fields = (
            "seat_id",
            "doptor_seat_id",
            "office_code",
            "designation_en",
            "designation_bn",
            "role_level",
            "incumbent_officer_id",
            "incumbent_name_en",
            "is_vacant",
            "is_occupied",
            "additional_charge_seat_id",
            "immediate_supervisor_seat_id",
            "doptor_hr_email",
            "is_active",
        )


class SeatRouteRequestSerializer(serializers.Serializer):
    target_seat_id = serializers.CharField(max_length=64)
    complaint_id = serializers.UUIDField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)


class DoptorVacancyAlertSerializer(serializers.ModelSerializer):
    vacant_seat_id = serializers.CharField(source="vacant_seat.doptor_seat_id", read_only=True)
    routed_to_seat_id = serializers.CharField(
        source="routed_to_seat.doptor_seat_id", read_only=True, default=None
    )

    class Meta:
        model = DoptorVacancyAlert
        fields = (
            "alert_id",
            "vacant_seat_id",
            "routed_to_seat_id",
            "complaint_id",
            "fallback_tier",
            "hr_dispatch_status",
            "payload",
            "created_at",
        )
