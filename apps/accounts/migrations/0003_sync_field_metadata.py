from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_part2_identity_whistleblower"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="nid_hash",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Salted SHA-256 hash of NID/Birth Registration for privacy-preserving dedup.",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="doptor_seat_id",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Currently occupied Doptor organogram seat ID synced at login.",
                max_length=64,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="doptor_role_level",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Active role level (APPELLATE, GRO, SUPERVISOR, FIELD_WORKER).",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="user",
            name="is_oversight_cell",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Grants privileged RBAC access to unseal whistleblower identities via Vault.",
            ),
        ),
        migrations.AlterField(
            model_name="citizenprofile",
            name="unified_citizen_token",
            field=models.CharField(
                db_index=True,
                help_text="Persistent Unified Citizen Token (UCT) bound to verified identity.",
                max_length=64,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="citizenprofile",
            name="pseudonymous_public_hash",
            field=models.CharField(
                db_index=True,
                help_text="Publicly safe SHA-256 pseudonymous hash stored on complaints.",
                max_length=64,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="citizenprofile",
            name="utility_accounts",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Saved utility consumer IDs (DESCO, DPDC, DWASA, TITAS, etc.) for auto-fill.",
            ),
        ),
        migrations.AlterField(
            model_name="citizenprofile",
            name="saved_documents",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Metadata & MinIO object keys for reusable citizen documents.",
            ),
        ),
        migrations.AlterField(
            model_name="whistleblowervaultrecord",
            name="wrapped_dek",
            field=models.TextField(
                help_text="Per-record 256-bit DEK wrapped by HashiCorp Vault Transit engine."
            ),
        ),
        migrations.AlterField(
            model_name="whistleblowervaultrecord",
            name="encrypted_payload",
            field=models.TextField(
                help_text="Base64 AES-256-GCM ciphertext of real citizen identity JSON."
            ),
        ),
    ]
