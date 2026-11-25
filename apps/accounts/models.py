import uuid
from django.core.validators import MaxValueValidator, MinValueValidator
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    """Unified identity model for Citizens, Doptor Officers, Oversight Cell, and System Admins."""

    class AccountType(models.TextChoices):
        CITIZEN = "CITIZEN", "Citizen"
        OFFICER = "OFFICER", "Government Officer (Doptor)"
        ARBITRATOR = "ARBITRATOR", "Cabinet Arbitration Officer"
        SYSTEM = "SYSTEM", "System / ESB Service Account"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account_type = models.CharField(
        max_length=16, choices=AccountType.choices, default=AccountType.CITIZEN, db_index=True
    )
    phone_number = models.CharField(max_length=20, blank=True, db_index=True)
    nid_hash = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Salted SHA-256 hash of NID/Birth Registration for privacy-preserving dedup.",
    )
    doptor_officer_id = models.CharField(max_length=64, blank=True, db_index=True)
    doptor_seat_id = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Currently occupied Doptor organogram seat ID synced at login.",
    )
    doptor_role_level = models.CharField(
        max_length=16,
        blank=True,
        db_index=True,
        help_text="Active role level (APPELLATE, GRO, SUPERVISOR, FIELD_WORKER).",
    )
    is_oversight_cell = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Grants privileged RBAC access to unseal whistleblower identities via Vault.",
    )
    preferred_language = models.CharField(max_length=5, default="bn")

    class Meta:
        db_table = "accounts_user"
        verbose_name = "User"
        verbose_name_plural = "Users"


class CitizenProfile(models.Model):
    """
    Verified citizen identity profile storing persistent UCT, pseudonymous public hash,
    auto-fill civic metadata, and private anti-abuse credibility & strike tracking.
    """

    class IdentityProvider(models.TextChoices):
        MYGOV_OIDC = "MYGOV_OIDC", "myGov OAuth 2.0 / OIDC"
        PORICHOY_NID = "PORICHOY_NID", "Porichoy NID Verification"
        BIRTH_REG = "BIRTH_REG", "Birth Registration (BDRIS)"
        MOBILE_OTP = "MOBILE_OTP", "Mobile OTP Only"

    STRIKE_PREMODERATION_THRESHOLD = 3

    profile_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name="citizen_profile"
    )
    unified_citizen_token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Persistent Unified Citizen Token (UCT) bound to verified identity.",
    )
    pseudonymous_public_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Publicly safe SHA-256 pseudonymous hash stored on complaints.",
    )
    identity_provider = models.CharField(
        max_length=24,
        choices=IdentityProvider.choices,
        default=IdentityProvider.MYGOV_OIDC,
        db_index=True,
    )
    identity_verified = models.BooleanField(default=False, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    nid_last4 = models.CharField(max_length=4, blank=True)
    birth_reg_last4 = models.CharField(max_length=4, blank=True)

    # Auto-fill citizen metadata
    saved_address_en = models.TextField(blank=True)
    saved_address_bn = models.TextField(blank=True)
    saved_bbs_geo_code = models.CharField(max_length=16, blank=True, db_index=True)
    utility_accounts = models.JSONField(
        default=dict,
        blank=True,
        help_text="Saved utility consumer IDs (DESCO, DPDC, DWASA, TITAS, etc.) for auto-fill.",
    )
    saved_documents = models.JSONField(
        default=list,
        blank=True,
        help_text="Metadata & MinIO object keys for reusable citizen documents.",
    )

    # Private trust & anti-abuse controls (never exposed to public views)
    credibility_score = models.FloatField(
        default=100.0,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)],
    )
    strike_count = models.PositiveSmallIntegerField(default=0, db_index=True)
    requires_manual_premoderation = models.BooleanField(default=False, db_index=True)
    priority_routing_eligible = models.BooleanField(default=True, db_index=True)
    last_strike_at = models.DateTimeField(null=True, blank=True)
    last_strike_reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_citizen_profile"
        indexes = [
            models.Index(
                fields=["requires_manual_premoderation", "priority_routing_eligible"],
                name="idx_citprof_moderation",
            ),
        ]

    def record_verified_false_filing(self, reason: str, penalty: float = 25.0) -> None:
        """
        Apply a verified false-filing strike to an NID-linked account.
        At 3 strikes: enforces mandatory manual pre-moderation and revokes priority routing.
        """
        self.strike_count += 1
        self.credibility_score = max(0.0, round(self.credibility_score - penalty, 2))
        self.last_strike_at = timezone.now()
        self.last_strike_reason = reason
        if self.strike_count >= self.STRIKE_PREMODERATION_THRESHOLD:
            self.requires_manual_premoderation = True
            self.priority_routing_eligible = False
        self.save(
            update_fields=[
                "strike_count",
                "credibility_score",
                "last_strike_at",
                "last_strike_reason",
                "requires_manual_premoderation",
                "priority_routing_eligible",
                "updated_at",
            ]
        )

    def __str__(self) -> str:
        return f"CitizenProfile({self.unified_citizen_token[:16]}... | strikes={self.strike_count})"


class MobileOTPChallenge(models.Model):
    """Short-lived, hashed Mobile OTP verification challenge for citizen onboarding/login."""

    class Purpose(models.TextChoices):
        LOGIN = "LOGIN", "Citizen Login"
        NID_BIND = "NID_BIND", "NID / Birth Reg Binding"
        COMPLAINT_VERIFY = "COMPLAINT_VERIFY", "Complaint Submission Verification"

    challenge_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=20, db_index=True)
    otp_hash = models.CharField(max_length=64)
    purpose = models.CharField(max_length=24, choices=Purpose.choices, default=Purpose.LOGIN)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_mobile_otp_challenge"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["phone_number", "purpose", "expires_at"], name="idx_otp_phone_exp"),
        ]

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None


class WhistleblowerVaultRecord(models.Model):
    """
    Envelope-encrypted real-identity mapping for anonymous/whistleblower complaints.
    Accessible strictly to Oversight Cell roles via HashiCorp Vault Transit unwrapping.
    """

    record_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint_id = models.UUIDField(unique=True, db_index=True)
    pseudonymous_public_hash = models.CharField(max_length=64, db_index=True)
    vault_key_name = models.CharField(max_length=128)
    wrapped_dek = models.TextField(
        help_text="Per-record 256-bit DEK wrapped by HashiCorp Vault Transit engine."
    )
    encrypted_payload = models.TextField(
        help_text="Base64 AES-256-GCM ciphertext of real citizen identity JSON."
    )
    nonce_b64 = models.CharField(max_length=64)
    unsealed_count = models.PositiveIntegerField(default=0)
    last_unsealed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="unsealed_whistleblower_records",
    )
    last_unsealed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "accounts_whistleblower_vault_record"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"WhistleblowerVaultRecord(complaint={self.complaint_id}, unsealed={self.unsealed_count})"
