import django.contrib.gis.db.models.fields
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0002_part3_workflow_statuses"),
    ]

    operations = [
        migrations.AlterField(
            model_name="complaint",
            name="tracking_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Human-readable national tracking code, e.g. BD-2026-DHK-0094821.",
                max_length=32,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="parent_case",
            field=models.ForeignKey(
                blank=True,
                help_text="Populated when a multi-department grievance is split into child cases.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="split_child_cases",
                to="complaints.complaint",
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="master_cluster",
            field=models.ForeignKey(
                blank=True,
                help_text="Points to the canonical complaint when spatially/semantically deduplicated.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="clustered_duplicates",
                to="complaints.complaint",
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="citizen_uct_hash",
            field=models.CharField(
                db_index=True,
                help_text="SHA-256 Unique Citizen Token hash (preserves anonymity while preventing spam).",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="geo_point",
            field=django.contrib.gis.db.models.fields.PointField(
                blank=True,
                geography=True,
                help_text="WGS84 geographic point (lon, lat) using PostGIS geography for meter-accurate distance.",
                null=True,
                srid=4326,
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="admin_geo_code",
            field=models.CharField(
                blank=True, db_index=True, help_text="BBS administrative geocode.", max_length=16
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="h3_hex_index",
            field=models.CharField(
                blank=True, db_index=True, help_text="Uber H3 resolution-9 hex index.", max_length=20
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="transfer_count",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Hard-capped at <= 2 transfers; a 3rd transfer forces Cabinet Arbitration.",
                validators=[django.core.validators.MaxValueValidator(2)],
            ),
        ),
        migrations.AlterField(
            model_name="complaint",
            name="hold_reference_id",
            field=models.CharField(
                blank=True,
                help_text="Mandatory e-GP tender ID, budget memo ID, or disaster gazette ID when on hold.",
                max_length=128,
            ),
        ),
        migrations.AlterField(
            model_name="resolutionreport",
            name="gps_verified_dist_m",
            field=models.FloatField(
                blank=True,
                help_text="Geodesic distance in meters between complaint geo_point and after-photo EXIF/GPS.",
                null=True,
                validators=[django.core.validators.MinValueValidator(0.0)],
            ),
        ),
    ]
