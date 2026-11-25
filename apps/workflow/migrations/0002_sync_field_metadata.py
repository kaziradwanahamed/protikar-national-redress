from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="workflowtracker",
            name="sla_total_seconds",
            field=models.PositiveIntegerField(
                help_text="Total statutory SLA duration in seconds (P1=4h, P2=48h, P3=7-15d, P4=30d)."
            ),
        ),
        migrations.AlterField(
            model_name="workflowtracker",
            name="field_worker_sub_deadline_at",
            field=models.DateTimeField(
                blank=True,
                help_text="70% SLA sub-deadline assigned to the field worker by Unit Supervisor.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="workflowtracker",
            name="citizen_verify_deadline_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="72-hour citizen verification window.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="workflowtracker",
            name="officer_rebuttal_deadline_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                help_text="48-hour Right of Reply window.",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="workflowtracker",
            name="p1_accepted_at",
            field=models.DateTimeField(
                blank=True,
                help_text="Timestamp when P1 emergency ticket was accepted (Accept-First, Dispute-Later).",
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="escalationevent",
            name="apa_scorecard_impact",
            field=models.FloatField(
                default=0.0,
                help_text="Annual Performance Agreement (APA) penalty delta (0.0 for warnings/cleared).",
            ),
        ),
        migrations.AlterField(
            model_name="ddccagendaitem",
            name="agenda_month",
            field=models.CharField(db_index=True, help_text="YYYY-MM format.", max_length=7),
        ),
    ]
