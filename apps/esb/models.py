import uuid
from django.db import models


class AgencyEndpoint(models.Model):
    """3-Tier National Interoperability Registry for ministries, utilities, and rural offices."""

    class IntegrationTier(models.TextChoices):
        TIER_1_REST_WEBHOOK = "TIER_1_REST_WEBHOOK", "Tier 1 — REST / GraphQL + Webhooks"
        TIER_2_DB_RPA_BRIDGE = "TIER_2_DB_RPA_BRIDGE", "Tier 2 — Legacy DB / RPA Bridge (10m Poll)"
        TIER_3_ZERO_IT = "TIER_3_ZERO_IT", "Tier 3 — Zero-IT Built-in Workspace (Union Parishad)"

    endpoint_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency_code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        help_text="Canonical agency code (e.g., GRS, D_NOTHI, 999, DESCO, DPDC, WASA, BRTA, DNCC, DSCC).",
    )
    agency_name = models.CharField(max_length=255)
    tier = models.CharField(max_length=24, choices=IntegrationTier.choices, db_index=True)
    webhook_url = models.URLField(max_length=1024, blank=True)
    hmac_secret = models.CharField(max_length=128, blank=True)
    polling_enabled = models.BooleanField(default=False, db_index=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "esb_agency_endpoint"
        ordering = ["tier", "agency_code"]

    def __str__(self) -> str:
        return f"{self.agency_code} [{self.tier}]"


class ESBDeliveryLog(models.Model):
    """Idempotent outbound & inbound ESB event ledger across Tier 1 and Tier 2 integrations."""

    class Direction(models.TextChoices):
        OUTBOUND = "OUTBOUND", "Outbound Dispatch"
        INBOUND = "INBOUND", "Inbound Webhook / Sync"

    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        DELIVERED = "DELIVERED", "Delivered"
        FAILED = "FAILED", "Failed"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"

    delivery_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    agency_code = models.CharField(max_length=32, db_index=True)
    direction = models.CharField(max_length=16, choices=Direction.choices, db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    complaint_id = models.UUIDField(null=True, blank=True, db_index=True)
    idempotency_key = models.CharField(max_length=128, unique=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    http_status = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    attempts = models.PositiveSmallIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "esb_delivery_log"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ESB({self.direction} {self.agency_code} | {self.event_type} | {self.status})"


class OmnichannelIntakeRecord(models.Model):
    """Tracks citizen grievance intake from WhatsApp, Messenger, and <140-byte 2G SMS/USSD."""

    class Channel(models.TextChoices):
        WHATSAPP = "WHATSAPP", "WhatsApp Bot Webhook"
        MESSENGER = "MESSENGER", "Facebook Messenger Bot Webhook"
        SMS_2G = "SMS_2G", "Degraded-Mode 2G SMS (<140 bytes)"
        USSD_2G = "USSD_2G", "Degraded-Mode 2G USSD (<140 bytes)"

    intake_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.CharField(max_length=16, choices=Channel.choices, db_index=True)
    sender_id = models.CharField(max_length=64, db_index=True)
    raw_payload = models.TextField()
    byte_length = models.PositiveIntegerField(default=0)
    parsed_fields = models.JSONField(default=dict, blank=True)
    complaint_id = models.UUIDField(null=True, blank=True, db_index=True)
    crisis_fastlane_triggered = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "esb_omnichannel_intake"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Intake({self.channel} | {self.sender_id} | {self.byte_length}B)"
