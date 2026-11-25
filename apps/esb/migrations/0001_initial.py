import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="AgencyEndpoint",
            fields=[
                ("endpoint_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("agency_code", models.CharField(db_index=True, max_length=32, unique=True)),
                ("agency_name", models.CharField(max_length=255)),
                (
                    "tier",
                    models.CharField(
                        choices=[
                            ("TIER_1_REST_WEBHOOK", "Tier 1 — REST / GraphQL + Webhooks"),
                            ("TIER_2_DB_RPA_BRIDGE", "Tier 2 — Legacy DB / RPA Bridge (10m Poll)"),
                            ("TIER_3_ZERO_IT", "Tier 3 — Zero-IT Built-in Workspace (Union Parishad)"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                ("webhook_url", models.URLField(blank=True, max_length=1024)),
                ("hmac_secret", models.CharField(blank=True, max_length=128)),
                ("polling_enabled", models.BooleanField(db_index=True, default=False)),
                ("last_synced_at", models.DateTimeField(blank=True, null=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "esb_agency_endpoint",
                "ordering": ["tier", "agency_code"],
            },
        ),
        migrations.CreateModel(
            name="ESBDeliveryLog",
            fields=[
                ("delivery_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("agency_code", models.CharField(db_index=True, max_length=32)),
                (
                    "direction",
                    models.CharField(
                        choices=[("OUTBOUND", "Outbound Dispatch"), ("INBOUND", "Inbound Webhook / Sync")],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("event_type", models.CharField(db_index=True, max_length=64)),
                ("complaint_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("idempotency_key", models.CharField(db_index=True, max_length=128, unique=True)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("http_status", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("QUEUED", "Queued"),
                            ("DELIVERED", "Delivered"),
                            ("FAILED", "Failed"),
                            ("ACKNOWLEDGED", "Acknowledged"),
                        ],
                        db_index=True,
                        default="QUEUED",
                        max_length=16,
                    ),
                ),
                ("attempts", models.PositiveSmallIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "db_table": "esb_delivery_log",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="OmnichannelIntakeRecord",
            fields=[
                ("intake_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "channel",
                    models.CharField(
                        choices=[
                            ("WHATSAPP", "WhatsApp Bot Webhook"),
                            ("MESSENGER", "Facebook Messenger Bot Webhook"),
                            ("SMS_2G", "Degraded-Mode 2G SMS (<140 bytes)"),
                            ("USSD_2G", "Degraded-Mode 2G USSD (<140 bytes)"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("sender_id", models.CharField(db_index=True, max_length=64)),
                ("raw_payload", models.TextField()),
                ("byte_length", models.PositiveIntegerField(default=0)),
                ("parsed_fields", models.JSONField(blank=True, default=dict)),
                ("complaint_id", models.UUIDField(blank=True, db_index=True, null=True)),
                ("crisis_fastlane_triggered", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
            options={
                "db_table": "esb_omnichannel_intake",
                "ordering": ["-created_at"],
            },
        ),
    ]
