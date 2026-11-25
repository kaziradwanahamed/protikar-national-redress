import uuid
import django.contrib.gis.db.models.fields
import django.core.validators
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("organogram", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Complaint",
            fields=[
                ("complaint_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("tracking_code", models.CharField(blank=True, db_index=True, max_length=32, unique=True)),
                ("citizen_uct_hash", models.CharField(db_index=True, max_length=64)),
                ("is_anonymous", models.BooleanField(db_index=True, default=False)),
                ("raw_text_bn", models.TextField(blank=True)),
                ("raw_text_en", models.TextField(blank=True)),
                ("voice_audio_url", models.URLField(blank=True, max_length=1024)),
                ("ai_category_code", models.CharField(blank=True, db_index=True, max_length=64)),
                (
                    "ai_confidence",
                    models.FloatField(
                        blank=True,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(1.0),
                        ],
                    ),
                ),
                (
                    "urgency_tier",
                    models.CharField(
                        choices=[
                            ("P1", "P1 — Critical / Life-Safety (6h SLA)"),
                            ("P2", "P2 — High / Essential Utility Outage (24h SLA)"),
                            ("P3", "P3 — Standard Service Delivery (72h SLA)"),
                            ("P4", "P4 — Routine / Long-Term Civic Request (15d SLA)"),
                        ],
                        db_index=True,
                        default="P3",
                        max_length=4,
                    ),
                ),
                (
                    "geo_point",
                    django.contrib.gis.db.models.fields.PointField(
                        blank=True, geography=True, null=True, srid=4326
                    ),
                ),
                ("admin_geo_code", models.CharField(blank=True, db_index=True, max_length=16)),
                ("h3_hex_index", models.CharField(blank=True, db_index=True, max_length=20)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("SUBMITTED", "Submitted"),
                            ("TRIAGED", "AI Triaged"),
                            ("ASSIGNED", "Assigned to Doptor Seat"),
                            ("IN_PROGRESS", "Work In Progress"),
                            ("ON_HOLD", "On Hold (Verified Reason)"),
                            ("ARBITRATION", "Cabinet / Inter-Agency Arbitration"),
                            ("RESOLVED_PENDING", "Resolved — Pending Citizen Verdict"),
                            ("CLOSED_ACCEPTED", "Closed — Citizen Accepted"),
                            ("REOPENED_REJECTED", "Reopened — Citizen Rejected"),
                            ("MERGED_DUPLICATE", "Merged into Master Cluster"),
                            ("DISASTER_FROZEN", "SLA Frozen (Active Crisis Zone)"),
                        ],
                        db_index=True,
                        default="SUBMITTED",
                        max_length=24,
                    ),
                ),
                ("sla_deadline_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("escalation_level", models.PositiveSmallIntegerField(db_index=True, default=0)),
                (
                    "transfer_count",
                    models.PositiveSmallIntegerField(
                        default=0, validators=[django.core.validators.MaxValueValidator(2)]
                    ),
                ),
                ("is_arbitration_locked", models.BooleanField(db_index=True, default=False)),
                ("crisis_zone_id", models.UUIDField(blank=True, db_index=True, null=True)),
                (
                    "hold_reason_code",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("EGP_TENDER", "e-GP Procurement / Tender In Progress"),
                            ("BUDGET_APPROVAL", "Annual Development Budget Approval"),
                            ("DISASTER_FREEZE", "Declared Disaster / Force Majeure Freeze"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                ("hold_reference_id", models.CharField(blank=True, max_length=128)),
                ("officer_rebuttal_url", models.URLField(blank=True, max_length=1024)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "master_cluster",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="clustered_duplicates",
                        to="complaints.complaint",
                    ),
                ),
                (
                    "parent_case",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="split_child_cases",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "complaints_complaint",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("log_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sequence_no", models.BigIntegerField(db_index=True, editable=False, unique=True)),
                ("actor_id", models.CharField(db_index=True, max_length=64)),
                ("actor_seat_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("actor_role", models.CharField(blank=True, max_length=32)),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("entity_type", models.CharField(default="Complaint", max_length=64)),
                ("entity_id", models.CharField(db_index=True, max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now, editable=False)),
                ("previous_hash", models.CharField(editable=False, max_length=64)),
                ("current_hash", models.CharField(db_index=True, editable=False, max_length=64, unique=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_logs",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "complaints_audit_log",
                "ordering": ["sequence_no"],
                "default_permissions": ("add", "view"),
            },
        ),
        migrations.CreateModel(
            name="ResolutionReport",
            fields=[
                ("report_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("submitted_by_seat", models.CharField(db_index=True, max_length=64)),
                ("work_summary", models.TextField()),
                ("after_photo_urls", models.JSONField(blank=True, default=list)),
                (
                    "gps_verified_dist_m",
                    models.FloatField(
                        blank=True,
                        null=True,
                        validators=[django.core.validators.MinValueValidator(0.0)],
                    ),
                ),
                (
                    "citizen_verdict",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending Citizen Verification"),
                            ("ACCEPTED", "Accepted by Citizen"),
                            ("REJECTED", "Rejected by Citizen"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("citizen_feedback", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resolution_reports",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "complaints_resolution_report",
                "ordering": ["-submitted_at"],
            },
        ),
        migrations.CreateModel(
            name="TicketAssignment",
            fields=[
                ("assignment_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("doptor_office_id", models.CharField(db_index=True, max_length=64)),
                ("doptor_seat_id", models.CharField(db_index=True, max_length=64)),
                ("assigned_officer_id", models.CharField(blank=True, db_index=True, max_length=64)),
                (
                    "role_level",
                    models.CharField(
                        choices=[
                            ("APPELLATE", "Appellate Officer"),
                            ("GRO", "Grievance Redress Officer (GRO)"),
                            ("SUPERVISOR", "Field Supervisor"),
                            ("FIELD_WORKER", "Field Worker"),
                        ],
                        db_index=True,
                        max_length=16,
                    ),
                ),
                ("assigned_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("due_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="assignments",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "complaints_ticket_assignment",
                "ordering": ["-assigned_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="complaint",
            constraint=models.CheckConstraint(
                condition=models.Q(("transfer_count__lte", 2)),
                name="ck_complaint_transfer_count_lte_2",
            ),
        ),
        migrations.AddConstraint(
            model_name="complaint",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("ai_confidence__isnull", True),
                    models.Q(("ai_confidence__gte", 0.0), ("ai_confidence__lte", 1.0)),
                    _connector="OR",
                ),
                name="ck_complaint_ai_confidence_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="complaint",
            constraint=models.CheckConstraint(
                condition=models.Q(("hold_reason_code", ""), models.Q(("hold_reference_id", ""), _negated=True), _connector="OR"),
                name="ck_complaint_hold_requires_reference",
            ),
        ),
        migrations.AddIndex(
            model_name="complaint",
            index=models.Index(fields=["status", "urgency_tier", "sla_deadline_at"], name="idx_cmp_sla_queue"),
        ),
        migrations.AddIndex(
            model_name="complaint",
            index=models.Index(fields=["admin_geo_code", "status", "created_at"], name="idx_cmp_bbs_status"),
        ),
        migrations.AddIndex(
            model_name="complaint",
            index=models.Index(fields=["h3_hex_index", "ai_category_code", "status"], name="idx_cmp_h3_cluster"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["complaint", "sequence_no"], name="idx_audit_cmp_seq"),
        ),
        migrations.AddIndex(
            model_name="auditlog",
            index=models.Index(fields=["action", "created_at"], name="idx_audit_action_ts"),
        ),
        migrations.AddIndex(
            model_name="resolutionreport",
            index=models.Index(fields=["complaint", "citizen_verdict"], name="idx_resrep_cmp_verdict"),
        ),
        migrations.AddConstraint(
            model_name="ticketassignment",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("complaint", "role_level"),
                name="uq_active_assignment_per_role",
            ),
        ),
        migrations.AddIndex(
            model_name="ticketassignment",
            index=models.Index(fields=["doptor_seat_id", "is_active", "due_at"], name="idx_assign_seat_inbox"),
        ),
        migrations.AddIndex(
            model_name="ticketassignment",
            index=models.Index(fields=["doptor_office_id", "role_level", "is_active"], name="idx_assign_office_role"),
        ),
    ]
