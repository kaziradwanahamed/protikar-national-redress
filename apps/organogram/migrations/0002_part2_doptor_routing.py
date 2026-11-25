import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organogram", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="doptoroffice",
            name="directorate_code",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="doptoroffice",
            name="district_code",
            field=models.CharField(blank=True, db_index=True, max_length=16),
        ),
        migrations.AddField(
            model_name="doptoroffice",
            name="division_code",
            field=models.CharField(blank=True, db_index=True, max_length=16),
        ),
        migrations.AddField(
            model_name="doptoroffice",
            name="last_synced_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="doptoroffice",
            name="upazila_code",
            field=models.CharField(blank=True, db_index=True, max_length=16),
        ),
        migrations.AlterField(
            model_name="doptoroffice",
            name="office_layer",
            field=models.CharField(
                choices=[
                    ("MINISTRY", "Ministry / Division"),
                    ("DIRECTORATE", "Directorate / Department"),
                    ("CITY_CORP", "City Corporation"),
                    ("UTILITY", "Utility Authority (WASA / DESCO / DPDC / TITAS)"),
                    ("ENGINEERING", "Road & Engineering Agency (RHD / LGED)"),
                    ("DIVISION", "Divisional Administration"),
                    ("DISTRICT", "District Administration (DC Office)"),
                    ("UPAZILA", "Upazila Administration (UNO Office)"),
                ],
                db_index=True,
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="doptorseat",
            name="additional_charge_seat",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="additional_charge_for_seats",
                to="organogram.doptorseat",
            ),
        ),
        migrations.AddField(
            model_name="doptorseat",
            name="doptor_hr_email",
            field=models.EmailField(blank=True, max_length=254),
        ),
        migrations.CreateModel(
            name="DoptorVacancyAlert",
            fields=[
                ("alert_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("complaint_id", models.UUIDField(blank=True, db_index=True, null=True)),
                (
                    "fallback_tier",
                    models.CharField(
                        choices=[
                            ("ADDITIONAL_CHARGE", "Routed to Additional Charge Seat"),
                            ("IMMEDIATE_SUPERVISOR", "Auto-Routed to Immediate Supervisor"),
                            ("UNRESOLVED", "No Occupied Seat Found in Chain"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                (
                    "hr_dispatch_status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Pending HR Dispatch"),
                            ("SENT", "Dispatched to Doptor HR"),
                            ("ACKNOWLEDGED", "Acknowledged by Doptor HR"),
                        ],
                        db_index=True,
                        default="PENDING",
                        max_length=16,
                    ),
                ),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "routed_to_seat",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="received_fallback_alerts",
                        to="organogram.doptorseat",
                    ),
                ),
                (
                    "vacant_seat",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vacancy_alerts",
                        to="organogram.doptorseat",
                    ),
                ),
            ],
            options={
                "db_table": "organogram_doptor_vacancy_alert",
                "ordering": ["-created_at"],
            },
        ),
    ]
