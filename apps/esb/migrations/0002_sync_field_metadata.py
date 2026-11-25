from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("esb", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="agencyendpoint",
            name="agency_code",
            field=models.CharField(
                db_index=True,
                help_text="Canonical agency code (e.g., GRS, D_NOTHI, 999, DESCO, DPDC, WASA, BRTA, DNCC, DSCC).",
                max_length=32,
                unique=True,
            ),
        ),
    ]
