import uuid
import django.contrib.gis.db.models.fields
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("complaints", "0002_part3_workflow_statuses"),
        ("organogram", "0002_part2_doptor_routing"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrisisZone",
            fields=[
                ("crisis_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("crisis_code", models.CharField(db_index=True, max_length=64, unique=True)),
                ("name_en", models.CharField(max_length=255)),
                ("name_bn", models.CharField(blank=True, max_length=255)),
                (
                    "disaster_type",
                    models.CharField(
                        choices=[
                            ("CYCLONE", "Cyclone / Storm Surge"),
                            ("FLOOD", "Monsoon / Riverine Flood"),
                            ("FLASH_FLOOD", "Haor / Flash Flood"),
                            ("EARTHQUAKE", "Earthquake"),
                            ("FIRE_INDUSTRIAL", "Major Urban / Industrial Fire"),
                            ("HEATWAVE", "Severe Heatwave / Health Crisis"),
                        ],
                        db_index=True,
                        default="FLOOD",
                        max_length=24,
                    ),
                ),
                (
                    "trigger_source",
                    models.CharField(
                        choices=[
                            ("AUTO_5X_VELOCITY", "Automatic 5x Rolling Velocity Circuit Breaker"),
                            ("MODMR_TOGGLE", "MoDMR Manual Emergency Toggle"),
                            ("DC_TOGGLE", "Deputy Commissioner (DC) Emergency Toggle"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                ("geom", django.contrib.gis.db.models.fields.MultiPolygonField(srid=4326)),
                ("baseline_rate_per_hour", models.FloatField(default=10.0)),
                ("peak_rate_per_hour", models.FloatField(default=0.0)),
                ("frozen_ticket_count", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("activated_by_seat", models.CharField(blank=True, max_length=64)),
                ("activated_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("deactivated_at", models.DateTimeField(blank=True, null=True)),
                (
                    "affected_area_polygon",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="crisis_zones",
                        to="organogram.serviceareapolygon",
                    ),
                ),
            ],
            options={
                "db_table": "disaster_crisis_zone",
                "ordering": ["-activated_at"],
            },
        ),
        migrations.CreateModel(
            name="EmergencyCommandDispatch",
            fields=[
                ("dispatch_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("citizen_phone", models.CharField(blank=True, max_length=24)),
                ("raw_message", models.TextField()),
                ("matched_rescue_keywords", models.JSONField(blank=True, default=list)),
                (
                    "geo_point",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, geography=True, null=True, srid=4326
                    ),
                ),
                ("h3_res8_index", models.CharField(blank=True, db_index=True, max_length=20)),
                ("target_responders", models.JSONField(blank=True, default=list)),
                ("kafka_topic", models.CharField(blank=True, max_length=128)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("STREAMED", "Streamed to Emergency Command"),
                            ("ACKNOWLEDGED", "Acknowledged by Responder"),
                            ("RESCUE_DISPATCHED", "Rescue Team Dispatched"),
                            ("RESOLVED", "Victim Rescued / Resolved"),
                        ],
                        db_index=True,
                        default="STREAMED",
                        max_length=24,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="emergency_dispatches",
                        to="complaints.complaint",
                    ),
                ),
                (
                    "crisis_zone",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="fastlane_dispatches",
                        to="disaster.crisiszone",
                    ),
                ),
            ],
            options={
                "db_table": "disaster_emergency_command_dispatch",
                "ordering": ["-created_at"],
            },
        ),
    ]
