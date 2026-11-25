# Generated manually for Part 14 (FR07 ComplaintProgressUpdate & FR09 CitizenNotification)

import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("complaints", "0003_sync_field_metadata"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ComplaintProgressUpdate",
            fields=[
                ("update_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("officer_seat_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("officer_name", models.CharField(blank=True, max_length=150)),
                ("message", models.TextField()),
                ("attachment_url", models.URLField(blank=True, max_length=1024)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="progress_updates",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "complaints_progress_update",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="CitizenNotification",
            fields=[
                ("notification_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("citizen_uct_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                (
                    "channel",
                    models.CharField(
                        choices=[("IN_APP", "In-App Alert"), ("SMS", "SMS Dispatch"), ("PUSH", "Web/Mobile Push")],
                        db_index=True,
                        default="IN_APP",
                        max_length=16,
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("SUBMITTED", "Grievance Submitted"),
                            ("ASSIGNED", "Assigned to Officer/Field"),
                            ("PROGRESS_UPDATE", "Officer Progress Update"),
                            ("PENDING_VERIFY", "Pending Citizen Two-Key Verification"),
                            ("ESCALATED", "Escalated / Reopened"),
                            ("CLOSED", "Resolved & Closed"),
                        ],
                        db_index=True,
                        default="SUBMITTED",
                        max_length=24,
                    ),
                ),
                ("title", models.CharField(max_length=200)),
                ("message", models.TextField()),
                ("sms_dispatch_status", models.CharField(default="SIMULATED_SENT", max_length=32)),
                ("is_read", models.BooleanField(db_index=True, default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="complaints.complaint",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="citizen_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "complaints_citizen_notification",
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["is_read", "created_at"], name="idx_notif_unread_created")],
            },
        ),
    ]
