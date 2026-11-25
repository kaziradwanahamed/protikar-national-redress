import django.contrib.gis.db.models.fields
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organogram", "0002_part2_doptor_routing"),
    ]

    operations = [
        migrations.AlterField(
            model_name="doptoroffice",
            name="doptor_office_id",
            field=models.CharField(
                db_index=True, help_text="Canonical Doptor Office ID.", max_length=64, unique=True
            ),
        ),
        migrations.AlterField(
            model_name="doptoroffice",
            name="bbs_geo_code",
            field=models.CharField(
                blank=True, db_index=True, help_text="BBS administrative geocode.", max_length=16
            ),
        ),
        migrations.AlterField(
            model_name="doptorseat",
            name="doptor_seat_id",
            field=models.CharField(
                db_index=True,
                help_text="Canonical Doptor Seat/Organogram ID.",
                max_length=64,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="doptorseat",
            name="parent_seat",
            field=models.ForeignKey(
                blank=True,
                help_text="Immediate supervisor seat (immediate_supervisor_seat_id) in Doptor hierarchy.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="subordinate_seats",
                to="organogram.doptorseat",
            ),
        ),
        migrations.AlterField(
            model_name="doptorseat",
            name="additional_charge_seat",
            field=models.ForeignKey(
                blank=True,
                help_text="Designated additional-charge seat when primary seat is vacant.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="additional_charge_for_seats",
                to="organogram.doptorseat",
            ),
        ),
        migrations.AlterField(
            model_name="doptorseat",
            name="doptor_hr_email",
            field=models.EmailField(
                blank=True,
                help_text="Doptor HR focal email for automated vacant-seat alerts.",
                max_length=254,
            ),
        ),
        migrations.AlterField(
            model_name="serviceareapolygon",
            name="bbs_geo_code",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="BBS 2/4/6/8-digit administrative geocode.",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="serviceareapolygon",
            name="default_gro_seat",
            field=models.ForeignKey(
                blank=True,
                help_text="Default GRO seat for automated point-in-polygon ticket routing.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="routed_service_areas",
                to="organogram.doptorseat",
            ),
        ),
        migrations.AlterField(
            model_name="serviceareapolygon",
            name="geom",
            field=django.contrib.gis.db.models.fields.MultiPolygonField(
                help_text="WGS84 (EPSG:4326) MultiPolygon boundary of the service or administrative zone.",
                srid=4326,
            ),
        ),
    ]
