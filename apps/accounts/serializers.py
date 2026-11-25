from rest_framework import serializers

from apps.accounts.models import CitizenProfile, MobileOTPChallenge


class MyGovCallbackSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=256)
    state = serializers.CharField(max_length=128, required=False, allow_blank=True)


class OTPRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)
    purpose = serializers.ChoiceField(
        choices=MobileOTPChallenge.Purpose.choices,
        default=MobileOTPChallenge.Purpose.LOGIN,
    )


class OTPVerifyIdentitySerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    phone_number = serializers.CharField(max_length=20)
    otp_code = serializers.CharField(min_length=6, max_length=6)
    nid_number = serializers.CharField(max_length=17, required=False, allow_blank=True)
    birth_reg_number = serializers.CharField(max_length=17, required=False, allow_blank=True)
    date_of_birth = serializers.CharField(max_length=16, required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("nid_number") and not attrs.get("birth_reg_number"):
            raise serializers.ValidationError(
                "Either nid_number or birth_reg_number is required for verification."
            )
        return attrs


class CitizenProfileSerializer(serializers.ModelSerializer):
    """Public/self citizen profile serializer exposing auto-fill metadata (never private scores)."""

    full_name = serializers.SerializerMethodField()
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)

    class Meta:
        model = CitizenProfile
        fields = (
            "profile_id",
            "full_name",
            "phone_number",
            "unified_citizen_token",
            "pseudonymous_public_hash",
            "identity_provider",
            "identity_verified",
            "verified_at",
            "nid_last4",
            "birth_reg_last4",
            "saved_address_en",
            "saved_address_bn",
            "saved_bbs_geo_code",
            "utility_accounts",
            "saved_documents",
            "requires_manual_premoderation",
            "priority_routing_eligible",
        )
        read_only_fields = (
            "profile_id",
            "unified_citizen_token",
            "pseudonymous_public_hash",
            "identity_provider",
            "identity_verified",
            "verified_at",
            "nid_last4",
            "birth_reg_last4",
            "requires_manual_premoderation",
            "priority_routing_eligible",
        )

    def get_full_name(self, obj: CitizenProfile) -> str:
        return obj.user.get_full_name() or obj.user.username


class RecordFalseFilingStrikeSerializer(serializers.Serializer):
    pseudonymous_public_hash = serializers.CharField(max_length=64)
    reason = serializers.CharField(min_length=10, max_length=1000)
    penalty = serializers.FloatField(default=25.0, min_value=5.0, max_value=100.0)


class WhistleblowerSealSerializer(serializers.Serializer):
    complaint_id = serializers.UUIDField()


class WhistleblowerUnsealSerializer(serializers.Serializer):
    justification = serializers.CharField(min_length=10, max_length=1000)
