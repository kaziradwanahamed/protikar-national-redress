from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.accounts.models import (
    CitizenProfile,
    MobileOTPChallenge,
    User,
    WhistleblowerVaultRecord,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "account_type",
        "doptor_officer_id",
        "doptor_seat_id",
        "doptor_role_level",
        "is_oversight_cell",
        "is_active",
    )
    list_filter = ("account_type", "doptor_role_level", "is_oversight_cell", "is_active", "is_staff")
    search_fields = ("username", "email", "phone_number", "doptor_officer_id", "doptor_seat_id")
    fieldsets = BaseUserAdmin.fieldsets + (
        (
            "National Identity, Doptor & Oversight",
            {
                "fields": (
                    "account_type",
                    "phone_number",
                    "nid_hash",
                    "doptor_officer_id",
                    "doptor_seat_id",
                    "doptor_role_level",
                    "is_oversight_cell",
                    "preferred_language",
                )
            },
        ),
    )


@admin.register(CitizenProfile)
class CitizenProfileAdmin(admin.ModelAdmin):
    list_display = (
        "unified_citizen_token",
        "user",
        "identity_provider",
        "identity_verified",
        "credibility_score",
        "strike_count",
        "requires_manual_premoderation",
        "priority_routing_eligible",
    )
    list_filter = (
        "identity_provider",
        "identity_verified",
        "requires_manual_premoderation",
        "priority_routing_eligible",
    )
    search_fields = ("unified_citizen_token", "pseudonymous_public_hash", "user__phone_number")
    readonly_fields = ("profile_id", "unified_citizen_token", "pseudonymous_public_hash", "created_at", "updated_at")


@admin.register(MobileOTPChallenge)
class MobileOTPChallengeAdmin(admin.ModelAdmin):
    list_display = ("challenge_id", "phone_number", "purpose", "attempts", "expires_at", "consumed_at")
    list_filter = ("purpose",)
    search_fields = ("phone_number",)
    readonly_fields = ("challenge_id", "otp_hash", "created_at")


@admin.register(WhistleblowerVaultRecord)
class WhistleblowerVaultRecordAdmin(admin.ModelAdmin):
    list_display = (
        "record_id",
        "complaint_id",
        "vault_key_name",
        "unsealed_count",
        "last_unsealed_by",
        "last_unsealed_at",
        "created_at",
    )
    readonly_fields = [f.name for f in WhistleblowerVaultRecord._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
