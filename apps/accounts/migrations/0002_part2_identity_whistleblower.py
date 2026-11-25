import uuid
import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="doptor_role_level",
            field=models.CharField(blank=True, db_index=True, max_length=16),
        ),
        migrations.AddField(
            model_name="user",
            name="doptor_seat_id",
            field=models.CharField(blank=True, db_index=True, max_length=64),
        ),
        migrations.AddField(
            model_name="user",
            name="is_oversight_cell",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.CreateModel(
            name="CitizenProfile",
            fields=[
                ("profile_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("unified_citizen_token", models.CharField(db_index=True, max_length=64, unique=True)),
                ("pseudonymous_public_hash", models.CharField(db_index=True, max_length=64, unique=True)),
                (
                    "identity_provider",
                    models.CharField(
                        choices=[
                            ("MYGOV_OIDC", "myGov OAuth 2.0 / OIDC"),
                            ("PORICHOY_NID", "Porichoy NID Verification"),
                            ("BIRTH_REG", "Birth Registration (BDRIS)"),
                            ("MOBILE_OTP", "Mobile OTP Only"),
                        ],
                        db_index=True,
                        default="MYGOV_OIDC",
                        max_length=24,
                    ),
                ),
                ("identity_verified", models.BooleanField(db_index=True, default=False)),
                ("verified_at", models.DateTimeField(blank=True, null=True)),
                ("nid_last4", models.CharField(blank=True, max_length=4)),
                ("birth_reg_last4", models.CharField(blank=True, max_length=4)),
                ("saved_address_en", models.TextField(blank=True)),
                ("saved_address_bn", models.TextField(blank=True)),
                ("saved_bbs_geo_code", models.CharField(blank=True, db_index=True, max_length=16)),
                ("utility_accounts", models.JSONField(blank=True, default=dict)),
                ("saved_documents", models.JSONField(blank=True, default=list)),
                (
                    "credibility_score",
                    models.FloatField(
                        default=100.0,
                        validators=[
                            django.core.validators.MinValueValidator(0.0),
                            django.core.validators.MaxValueValidator(100.0),
                        ],
                    ),
                ),
                ("strike_count", models.PositiveSmallIntegerField(db_index=True, default=0)),
                ("requires_manual_premoderation", models.BooleanField(db_index=True, default=False)),
                ("priority_routing_eligible", models.BooleanField(db_index=True, default=True)),
                ("last_strike_at", models.DateTimeField(blank=True, null=True)),
                ("last_strike_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="citizen_profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "accounts_citizen_profile",
            },
        ),
        migrations.CreateModel(
            name="MobileOTPChallenge",
            fields=[
                ("challenge_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("phone_number", models.CharField(db_index=True, max_length=20)),
                ("otp_hash", models.CharField(max_length=64)),
                (
                    "purpose",
                    models.CharField(
                        choices=[
                            ("LOGIN", "Citizen Login"),
                            ("NID_BIND", "NID / Birth Reg Binding"),
                            ("COMPLAINT_VERIFY", "Complaint Submission Verification"),
                        ],
                        default="LOGIN",
                        max_length=24,
                    ),
                ),
                ("attempts", models.PositiveSmallIntegerField(default=0)),
                ("max_attempts", models.PositiveSmallIntegerField(default=5)),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "accounts_mobile_otp_challenge",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="WhistleblowerVaultRecord",
            fields=[
                ("record_id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("complaint_id", models.UUIDField(db_index=True, unique=True)),
                ("pseudonymous_public_hash", models.CharField(db_index=True, max_length=64)),
                ("vault_key_name", models.CharField(max_length=128)),
                ("wrapped_dek", models.TextField()),
                ("encrypted_payload", models.TextField()),
                ("nonce_b64", models.CharField(max_length=64)),
                ("unsealed_count", models.PositiveIntegerField(default=0)),
                ("last_unsealed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "last_unsealed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="unsealed_whistleblower_records",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "accounts_whistleblower_vault_record",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="citizenprofile",
            index=models.Index(
                fields=["requires_manual_premoderation", "priority_routing_eligible"],
                name="idx_citprof_moderation",
            ),
        ),
        migrations.AddIndex(
            model_name="mobileotpchallenge",
            index=models.Index(fields=["phone_number", "purpose", "expires_at"], name="idx_otp_phone_exp"),
        ),
    ]
