import uuid
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("complaints", "0002_part3_workflow_statuses"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArbitrationCase",
            fields=[
                ("arbitration_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "jurisdiction_scope",
                    models.CharField(
                        choices=[
                            ("UPAZILA_UNO", "Upazila Nirbahi Officer (UNO — Intra-Upazila)"),
                            ("DISTRICT_DC", "Deputy Commissioner (DC — Intra-District)"),
                            ("DIVISIONAL_CABINET", "Divisional Commissioner / Cabinet Cell (Inter-Agency)"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                ("arbitrator_seat_id", models.CharField(db_index=True, max_length=64)),
                ("decision_sla_deadline_at", models.DateTimeField(db_index=True)),
                ("disputing_seats", models.JSONField(blank=True, default=list)),
                ("ruling_assigned_seat_id", models.CharField(blank=True, max_length=64)),
                ("ruling_notes", models.TextField(blank=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "complaint",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="arbitration_case",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_arbitration_case",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="CapitalMilestone",
            fields=[
                ("milestone_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("BUDGET_APPROVED", "1. Budget Approved"),
                            ("EGP_TENDER_FLOATED", "2. e-GP Tender Floated"),
                            ("WORK_ORDER_ISSUED", "3. Work Order Issued"),
                            ("EXECUTION", "4. Physical Execution"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                ("stage_order", models.PositiveSmallIntegerField(default=1)),
                (
                    "reference_type",
                    models.CharField(
                        choices=[("EGP_TENDER", "e-GP Tender ID"), ("D_NOTHI", "D-Nothi Reference")],
                        max_length=16,
                    ),
                ),
                ("reference_id", models.CharField(db_index=True, max_length=128)),
                ("notes", models.TextField(blank=True)),
                ("is_completed", models.BooleanField(db_index=True, default=False)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("updated_by_seat", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="capital_milestones",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_capital_milestone",
                "ordering": ["complaint", "stage_order"],
            },
        ),
        migrations.CreateModel(
            name="EscalationEvent",
            fields=[
                ("event_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("YELLOW_WARNING_80", "80% SLA Yellow Warning to Supervisor"),
                            ("SLA_BREACH_100", "100% SLA Breach Auto-Escalation"),
                            ("CITIZEN_REJECTION", "Citizen Rejection Auto-Escalation"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                (
                    "escalation_tier",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "Tier 1 — Field / Unit Supervisor / GRO"),
                            (2, "Tier 2 — District DC / Executive Engineer"),
                            (3, "Tier 3 — Divisional Commissioner / Director General"),
                            (4, "Tier 4 — Ministry Secretary / Cabinet Cell"),
                        ],
                        db_index=True,
                    ),
                ),
                ("from_seat_id", models.CharField(blank=True, max_length=64)),
                ("to_seat_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("apa_scorecard_impact", models.FloatField(default=0.0)),
                ("ddcc_flagged", models.BooleanField(db_index=True, default=False)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="escalation_events",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_escalation_event",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="DDCCAgendaItem",
            fields=[
                ("agenda_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("district_bbs_code", models.CharField(db_index=True, max_length=16)),
                ("agenda_month", models.CharField(db_index=True, max_length=7)),
                ("summary", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("SCHEDULED", "Scheduled for Monthly DDCC"),
                            ("REVIEWED", "Reviewed in DDCC Session"),
                            ("RESOLVED", "Resolved Post-DDCC Directive"),
                        ],
                        db_index=True,
                        default="SCHEDULED",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "complaint",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ddcc_agenda_items",
                        to="complaints.complaint",
                    ),
                ),
                (
                    "escalation_event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="ddcc_items",
                        to="workflow.escalationevent",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_ddcc_agenda_item",
                "ordering": ["-agenda_month", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="WorkflowTracker",
            fields=[
                ("tracker_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("sla_started_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("sla_total_seconds", models.PositiveIntegerField()),
                ("sla_paused_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("sla_accumulated_pause_seconds", models.PositiveIntegerField(default=0)),
                ("acknowledged_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("auto_acknowledged", models.BooleanField(default=False)),
                ("field_worker_sub_deadline_at", models.DateTimeField(blank=True, null=True)),
                ("yellow_warning_sent_at", models.DateTimeField(blank=True, null=True)),
                ("pending_citizen_verify_at", models.DateTimeField(blank=True, null=True)),
                ("citizen_verify_deadline_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("auto_closed_audit_flag", models.BooleanField(db_index=True, default=False)),
                ("officer_rebuttal_deadline_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("p1_accepted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "complaint",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="workflow_tracker",
                        to="complaints.complaint",
                    ),
                ),
            ],
            options={
                "db_table": "workflow_tracker",
            },
        ),
        migrations.AddConstraint(
            model_name="capitalmilestone",
            constraint=models.UniqueConstraint(fields=("complaint", "stage"), name="uq_capital_milestone_per_stage"),
        ),
        migrations.AddConstraint(
            model_name="ddccagendaitem",
            constraint=models.UniqueConstraint(fields=("complaint", "agenda_month"), name="uq_ddcc_complaint_month"),
        ),
        migrations.AddIndex(
            model_name="workflowtracker",
            index=models.Index(fields=["citizen_verify_deadline_at", "auto_closed_audit_flag"], name="idx_wf_verify_deadline"),
        ),
        migrations.AddIndex(
            model_name="workflowtracker",
            index=models.Index(fields=["acknowledged_at", "sla_started_at"], name="idx_wf_ack_check"),
        ),
    ]
