from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="complaint",
            name="status",
            field=models.CharField(
                choices=[
                    ("SUBMITTED", "Submitted"),
                    ("ROUTED", "Routed to Doptor Seat"),
                    ("TRANSFERRED", "Transferred (Within 15% SLA Window)"),
                    ("ARBITRATION_LOCKED", "Arbitration Locked (Max Transfers Reached)"),
                    ("IN_PROGRESS", "Work In Progress"),
                    ("ON_HOLD_PROCUREMENT", "On Hold — Verified Procurement / e-GP"),
                    ("DISASTER_SLA_SUSPENDED", "SLA Suspended — Declared Disaster Zone"),
                    ("PENDING_CITIZEN_VERIFY", "Pending Citizen Verification (72h)"),
                    ("CONTESTED_BY_OFFICER", "Contested by Officer (48h Right of Reply)"),
                    ("UNFOUNDED_CLEARED", "Unfounded — Officer Cleared"),
                    ("CLOSED", "Closed"),
                    ("TRIAGED", "AI Triaged"),
                    ("ASSIGNED", "Assigned to Doptor Seat"),
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
                max_length=32,
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="urgency_tier",
            field=models.CharField(
                choices=[
                    ("P1", "P1 — Emergency / Life-Safety (4h SLA)"),
                    ("P2", "P2 — Urgent / Essential Utility Outage (48h SLA)"),
                    ("P3", "P3 — Standard Service Delivery (7–15d SLA)"),
                    ("P4", "P4 — Infrastructure / Policy Request (30d SLA)"),
                ],
                db_index=True,
                default="P3",
                max_length=4,
            ),
        ),
    ]
