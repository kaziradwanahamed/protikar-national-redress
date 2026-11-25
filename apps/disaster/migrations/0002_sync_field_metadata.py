import django.contrib.gis.db.models.fields
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("disaster", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="crisiszone",
            name="geom",
            field=django.contrib.gis.db.models.fields.MultiPolygonField(
                help_text="WGS84 MultiPolygon defining the active disaster surge boundary.",
                srid=4326,
            ),
        ),
    ]
