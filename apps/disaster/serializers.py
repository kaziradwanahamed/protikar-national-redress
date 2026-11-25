from rest_framework import serializers

from apps.disaster.models import CrisisZone, EmergencyCommandDispatch


class CrisisToggleSerializer(serializers.Serializer):
    crisis_code = serializers.CharField(max_length=64)
    action = serializers.ChoiceField(choices=["ACTIVATE", "DEACTIVATE"])
    name_en = serializers.CharField(max_length=255, required=False, default="Emergency Crisis Zone")
    name_bn = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    disaster_type = serializers.ChoiceField(
        choices=CrisisZone.DisasterType.choices, default=CrisisZone.DisasterType.CYCLONE
    )
    trigger_source = serializers.ChoiceField(
        choices=[CrisisZone.TriggerSource.MODMR_TOGGLE, CrisisZone.TriggerSource.DC_TOGGLE],
        default=CrisisZone.TriggerSource.MODMR_TOGGLE,
    )
    zone_code = serializers.CharField(max_length=64, required=False, allow_blank=True)


class SurgeIngestSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90.0, max_value=90.0)
    lon = serializers.FloatField(min_value=-180.0, max_value=180.0)
    message = serializers.CharField(max_length=2000)
    citizen_phone = serializers.CharField(max_length=24, required=False, allow_blank=True, default="")
    crisis_id = serializers.UUIDField(required=False, allow_null=True)


class EmergencyCommandDispatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyCommandDispatch
        fields = (
            "dispatch_id",
            "crisis_zone",
            "citizen_phone",
            "raw_message",
            "matched_rescue_keywords",
            "h3_res8_index",
            "target_responders",
            "kafka_topic",
            "status",
            "created_at",
        )
