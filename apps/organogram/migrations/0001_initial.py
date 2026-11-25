import uuid
import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="DoptorOffice",
            fields=[
                ("office_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("doptor_office_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("office_code", models.CharField(db_index=True, max_length=64, unique=True)),
                ("name_en", models.CharField(max_length=255)),
                ("name_bn", models.CharField(blank=True, max_length=255)),
                (
                    "office_layer",
                    models.CharField(
                        choices=[
                            ("MINISTRY", "Ministry / Division"),
                            ("DIRECTORATE", "Directorate / Department"),
                            ("CITY_CORP", "City Corporation"),
                            ("UTILITY", "Utility Authority (WASA / DESCO / DPDC / TITAS)"),
                            ("ENGINEERING", "Road & Engineering Agency (RHD / LGED)"),
                            ("DISTRICT", "District Administration (DC Office)"),
                            ("UPAZILA", "Upazila Administration (UNO Office)"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                ("ministry_code", models.CharField(blank=True, db_index=True, max_length=64)),
                ("bbs_geo_code", models.CharField(blank=True, db_index=True, max_length=16)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "parent_office",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="child_offices",
                        to="organogram.doptoroffice",
                    ),
                ),
            ],
            options={
                "db_table": "organogram_doptor_office",
                "ordering": ["office_layer", "name_en"],
            },
        ),
        migrations.CreateModel(
            name="DoptorSeat",
            fields=[
                ("seat_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("doptor_seat_id", models.CharField(db_index=True, max_length=64, unique=True)),
                ("designation_en", models.CharField(max_length=255)),
                ("designation_bn", models.CharField(blank=True, max_length=255)),
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
                ("incumbent_officer_id", models.CharField(blank=True, db_index=True, max_length=64)),
                ("incumbent_name_en", models.CharField(blank=True, max_length=255)),
                ("incumbent_name_bn", models.CharField(blank=True, max_length=255)),
                ("is_vacant", models.BooleanField(db_index=True, default=False)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "office",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="seats",
                        to="organogram.doptoroffice",
                    ),
                ),
                (
                    "parent_seat",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subordinate_seats",
                        to="organogram.doptorseat",
                    ),
                ),
            ],
            options={
                "db_table": "organogram_doptor_seat",
                "ordering": ["office", "role_level", "designation_en"],
            },
        ),
        migrations.CreateModel(
            name="ServiceAreaPolygon",
            fields=[
                ("area_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("zone_code", models.CharField(db_index=True, max_length=64, unique=True)),
                (
                    "zone_type",
                    models.CharField(
                        choices=[
                            ("BBS_DIVISION", "BBS Division"),
                            ("BBS_DISTRICT", "BBS District (Zila)"),
                            ("BBS_UPAZILA", "BBS Upazila / Thana"),
                            ("BBS_UNION", "BBS Union / Pourashava"),
                            ("CITY_CORP_WARD", "City Corporation Ward (DNCC/DSCC/CCC)"),
                            ("WASA_MODS_ZONE", "WASA MODS Zone"),
                            ("DESCO_FEEDER", "DESCO Feeder / S&D Zone"),
                            ("DPDC_FEEDER", "DPDC Feeder / NOCS Zone"),
                            ("RHD_ROAD", "RHD National/Regional Highway Corridor"),
                            ("LGED_ROAD", "LGED Upazila/Union Road Corridor"),
                            ("DISASTER_ZONE", "Disaster / Crisis Freeze Zone"),
                        ],
                        db_index=True,
                        max_length=24,
                    ),
                ),
                ("bbs_geo_code", models.CharField(blank=True, db_index=True, max_length=16)),
                ("name_en", models.CharField(max_length=255)),
                ("name_bn", models.CharField(blank=True, max_length=255)),
                ("geom", django.contrib.gis.db.models.fields.MultiPolygonField(srid=4326)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "default_gro_seat",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="routed_service_areas",
                        to="organogram.doptorseat",
                    ),
                ),
                (
                    "parent_area",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="child_areas",
                        to="organogram.serviceareapolygon",
                    ),
                ),
                (
                    "primary_office",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="service_areas",
                        to="organogram.doptoroffice",
                    ),
                ),
            ],
            options={
                "db_table": "organogram_service_area_polygon",
                "ordering": ["zone_type", "zone_code"],
            },
        ),
        migrations.AddIndex(
            model_name="doptoroffice",
            index=models.Index(fields=["office_layer", "is_active"], name="idx_office_layer_active"),
        ),
        migrations.AddIndex(
            model_name="doptoroffice",
            index=models.Index(fields=["bbs_geo_code", "office_layer"], name="idx_office_bbs_layer"),
        ),
        migrations.AddIndex(
            model_name="doptorseat",
            index=models.Index(fields=["office", "role_level", "is_active"], name="idx_seat_office_role"),
        ),
        migrations.AddIndex(
            model_name="serviceareapolygon",
            index=models.Index(fields=["zone_type", "is_active"], name="idx_sap_type_active"),
        ),
        migrations.AddIndex(
            model_name="serviceareapolygon",
            index=models.Index(fields=["bbs_geo_code", "zone_type"], name="idx_sap_bbs_type"),
        ),
    ]
