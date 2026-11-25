from rest_framework import serializers

from apps.esb.models import OmnichannelIntakeRecord


class Tier1OutboundDispatchSerializer(serializers.Serializer):
    agency_code = serializers.CharField(max_length=32)
    event_type = serializers.CharField(max_length=64, default="COMPLAINT_ROUTED")
    complaint_id = serializers.UUIDField()


class Tier3RuralUpdateSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()
    update_note = serializers.CharField(min_length=5, max_length=2000)


class SocialBotWebhookSerializer(serializers.Serializer):
    sender_id = serializers.CharField(max_length=64)
    text = serializers.CharField(required=False, allow_blank=True, default="")
    voice_audio_url = serializers.URLField(required=False, allow_blank=True, default="")
    lat = serializers.FloatField(required=False, allow_null=True)
    lon = serializers.FloatField(required=False, allow_null=True)


class Compact2GIntakeSerializer(serializers.Serializer):
    sender_phone = serializers.CharField(max_length=24)
    raw_payload = serializers.CharField(max_length=200)
    channel = serializers.ChoiceField(
        choices=[OmnichannelIntakeRecord.Channel.SMS_2G, OmnichannelIntakeRecord.Channel.USSD_2G],
        default=OmnichannelIntakeRecord.Channel.SMS_2G,
    )
