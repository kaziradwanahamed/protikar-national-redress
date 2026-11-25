import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("complaints", "0002_part3_workflow_statuses"),
    ]

    operations = [
        migrations.CreateModel(
            name="MasterIncidentSubscription",
            fields=[
                ("subscription_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("citizen_uct_hash", models.CharField(db_index=True, max_length=64)),
                (
                    "notify_channel",
                    models.CharField(
                        choices=[
                            ("SMS", "SMS Alert"),
                            ("PUSH", "Mobile Push Notification"),
                            ("WEB", "Web Portal Live Feed"),
                        ],
                        default="SMS",
                        max_length=16,
                    ),
                ),
                ("subscribed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "duplicate_complaint",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="master_subscription_links",
                        to="complaints.complaint",
                    ),
                ),
                (
                    "master_complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="cluster_subscriptions",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "ai_triage_master_incident_subscription",
            },
        ),
        migrations.CreateModel(
            name="SubTicketDependency",
            fields=[
                ("dependency_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sequence_order", models.PositiveSmallIntegerField(default=1)),
                ("reason", models.CharField(max_length=255)),
                ("is_satisfied", models.BooleanField(db_index=True, default=False)),
                ("satisfied_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dependent_ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocked_by_prerequisites",
                        to="complaints.complaint",
                    ),
                ),
                (
                    "parent_case",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="subticket_dependencies",
                        to="complaints.complaint",
                    ),
                ),
                (
                    "prerequisite_ticket",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="blocking_dependents",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "ai_triage_subticket_dependency",
                "ordering": ["parent_case", "sequence_order"],
            },
        ),
        migrations.CreateModel(
            name="TriageRun",
            fields=[
                ("run_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("asr_transcript_bn", models.TextField(blank=True)),
                ("asr_transcript_en", models.TextField(blank=True)),
                ("detected_dialect", models.CharField(blank=True, max_length=32)),
                ("vlm_evidence_valid", models.BooleanField(default=True)),
                ("vlm_evidence_labels", models.JSONField(blank=True, default=list)),
                ("ocr_extracted_refs", models.JSONField(blank=True, default=dict)),
                ("primary_ministry_code", models.CharField(blank=True, db_index=True, max_length=64)),
                ("primary_agency_code", models.CharField(blank=True, db_index=True, max_length=64)),
                ("predicted_labels", models.JSONField(blank=True, default=list)),
                ("confidence_score", models.FloatField(default=0.0)),
                (
                    "routing_decision",
                    models.CharField(
                        choices=[
                            ("AUTO_ROUTED", "Auto-Routed Immediately (>=85%)"),
                            ("GRO_REASSIGN_FLAGGED", "Routed with 1-Click GRO Reassign Flag (60-84%)"),
                            ("CLARIFICATION_REQUIRED", "Clarifying Questions Returned (<60%)"),
                            ("COMPOUND_SPLIT", "Split into Parent + Dependent Child Sub-Tickets"),
                            ("MERGED_DUPLICATE", "Merged into Spatial Master Incident (<=200m)"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                ("gro_one_click_reassign_flag", models.BooleanField(db_index=True, default=False)),
                ("clarifying_questions", models.JSONField(blank=True, default=list)),
                ("extracted_geo_entities", models.JSONField(blank=True, default=list)),
                ("resolved_zone_codes", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="triage_runs",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "ai_triage_run",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="masterincidentsubscription",
            constraint=models.UniqueConstraint(
                fields=("master_complaint", "citizen_uct_hash"),
                name="uq_master_incident_unique_citizen",
            ),
        ),
        migrations.AddConstraint(
            model_name="subticketdependency",
            constraint=models.UniqueConstraint(
                fields=("prerequisite_ticket", "dependent_ticket"),
                name="uq_subticket_dependency_edge",
            ),
        ),
    ]
