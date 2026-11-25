import hashlib
import json
import secrets
import uuid

from django.contrib.gis.db import models as gis_models
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import CheckConstraint, Q, UniqueConstraint
from django.utils import timezone

from apps.organogram.models import RoleLevel


class AuditLogImmutabilityError(PermissionError):
    """Raised whenever code attempts to mutate or delete an AuditLog ledger row."""


class Complaint(gis_models.Model):
    """Core national citizen grievance record with GeoDjango geography and SLA controls."""

    class UrgencyTier(models.TextChoices):
        P1 = "P1", "P1 — Emergency / Life-Safety (4h SLA)"
        P2 = "P2", "P2 — Urgent / Essential Utility Outage (48h SLA)"
        P3 = "P3", "P3 — Standard Service Delivery (7–15d SLA)"
        P4 = "P4", "P4 — Infrastructure / Policy Request (30d SLA)"

    class ComplaintStatus(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        ROUTED = "ROUTED", "Routed to Doptor Seat"
        TRANSFERRED = "TRANSFERRED", "Transferred (Within 15% SLA Window)"
        ARBITRATION_LOCKED = "ARBITRATION_LOCKED", "Arbitration Locked (Max Transfers Reached)"
        IN_PROGRESS = "IN_PROGRESS", "Work In Progress"
        ON_HOLD_PROCUREMENT = "ON_HOLD_PROCUREMENT", "On Hold — Verified Procurement / e-GP"
        DISASTER_SLA_SUSPENDED = "DISASTER_SLA_SUSPENDED", "SLA Suspended — Declared Disaster Zone"
        PENDING_CITIZEN_VERIFY = "PENDING_CITIZEN_VERIFY", "Pending Citizen Verification (72h)"
        CONTESTED_BY_OFFICER = "CONTESTED_BY_OFFICER", "Contested by Officer (48h Right of Reply)"
        UNFOUNDED_CLEARED = "UNFOUNDED_CLEARED", "Unfounded — Officer Cleared"
        CLOSED = "CLOSED", "Closed"
        # Legacy aliases preserved for Part 1/2 backward compatibility
        TRIAGED = "TRIAGED", "AI Triaged"
        ASSIGNED = "ASSIGNED", "Assigned to Doptor Seat"
        ON_HOLD = "ON_HOLD", "On Hold (Verified Reason)"
        ARBITRATION = "ARBITRATION", "Cabinet / Inter-Agency Arbitration"
        RESOLVED_PENDING = "RESOLVED_PENDING", "Resolved — Pending Citizen Verdict"
        CLOSED_ACCEPTED = "CLOSED_ACCEPTED", "Closed — Citizen Accepted"
        REOPENED_REJECTED = "REOPENED_REJECTED", "Reopened — Citizen Rejected"
        MERGED_DUPLICATE = "MERGED_DUPLICATE", "Merged into Master Cluster"
        DISASTER_FROZEN = "DISASTER_FROZEN", "SLA Frozen (Active Crisis Zone)"

    class HoldReasonCode(models.TextChoices):
        EGP_TENDER = "EGP_TENDER", "e-GP Procurement / Tender In Progress"
        BUDGET_APPROVAL = "BUDGET_APPROVAL", "Annual Development Budget Approval"
        DISASTER_FREEZE = "DISASTER_FREEZE", "Declared Disaster / Force Majeure Freeze"

    complaint_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tracking_code = models.CharField(
        max_length=32,
        unique=True,
        db_index=True,
        blank=True,
        help_text="Human-readable national tracking code, e.g. BD-2026-DHK-0094821.",
    )
    parent_case = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="split_child_cases",
        help_text="Populated when a multi-department grievance is split into child cases.",
    )
    master_cluster = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="clustered_duplicates",
        help_text="Points to the canonical complaint when spatially/semantically deduplicated.",
    )
    citizen_uct_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 Unique Citizen Token hash (preserves anonymity while preventing spam).",
    )
    is_anonymous = models.BooleanField(default=False, db_index=True)

    # Multimodal Grievance Payload
    raw_text_bn = models.TextField(blank=True)
    raw_text_en = models.TextField(blank=True)
    voice_audio_url = models.URLField(max_length=1024, blank=True)

    # AI Triage & Urgency Classification
    ai_category_code = models.CharField(max_length=64, blank=True, db_index=True)
    ai_confidence = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
    )
    urgency_tier = models.CharField(
        max_length=4, choices=UrgencyTier.choices, default=UrgencyTier.P3, db_index=True
    )

    # Geospatial Coordinates & BBS/H3 Indexing
    geo_point = gis_models.PointField(
        geography=True,
        srid=4326,
        null=True,
        blank=True,
        spatial_index=True,
        help_text="WGS84 geographic point (lon, lat) using PostGIS geography for meter-accurate distance.",
    )
    admin_geo_code = models.CharField(
        max_length=16, blank=True, db_index=True, help_text="BBS administrative geocode."
    )
    h3_hex_index = models.CharField(
        max_length=20, blank=True, db_index=True, help_text="Uber H3 resolution-9 hex index."
    )

    # Workflow, SLA, Escalation & Anti-Ping-Pong Controls
    status = models.CharField(
        max_length=32,
        choices=ComplaintStatus.choices,
        default=ComplaintStatus.SUBMITTED,
        db_index=True,
    )
    sla_deadline_at = models.DateTimeField(null=True, blank=True, db_index=True)
    escalation_level = models.PositiveSmallIntegerField(default=0, db_index=True)
    transfer_count = models.PositiveSmallIntegerField(
        default=0,
        validators=[MaxValueValidator(2)],
        help_text="Hard-capped at <= 2 transfers; a 3rd transfer forces Cabinet Arbitration.",
    )
    is_arbitration_locked = models.BooleanField(default=False, db_index=True)
    crisis_zone_id = models.UUIDField(null=True, blank=True, db_index=True)

    # Verified Hold & Officer Rebuttal
    hold_reason_code = models.CharField(
        max_length=24, choices=HoldReasonCode.choices, blank=True, db_index=True
    )
    hold_reference_id = models.CharField(
        max_length=128,
        blank=True,
        help_text="Mandatory e-GP tender ID, budget memo ID, or disaster gazette ID when on hold.",
    )
    officer_rebuttal_url = models.URLField(max_length=1024, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "complaints_complaint"
        ordering = ["-created_at"]
        constraints = [
            CheckConstraint(
                condition=Q(transfer_count__lte=2),
                name="ck_complaint_transfer_count_lte_2",
            ),
            CheckConstraint(
                condition=Q(ai_confidence__isnull=True)
                | (Q(ai_confidence__gte=0.0) & Q(ai_confidence__lte=1.0)),
                name="ck_complaint_ai_confidence_range",
            ),
            CheckConstraint(
                condition=Q(hold_reason_code="") | ~Q(hold_reference_id=""),
                name="ck_complaint_hold_requires_reference",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "urgency_tier", "sla_deadline_at"],
                name="idx_cmp_sla_queue",
            ),
            models.Index(
                fields=["admin_geo_code", "status", "created_at"],
                name="idx_cmp_bbs_status",
            ),
            models.Index(
                fields=["h3_hex_index", "ai_category_code", "status"],
                name="idx_cmp_h3_cluster",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.transfer_count > 2:
            raise ValidationError({"transfer_count": "Transfer count cannot exceed 2."})
        if self.hold_reason_code and not self.hold_reference_id:
            raise ValidationError(
                {"hold_reference_id": "A hold reference ID is required when hold_reason_code is set."}
            )
        if not (self.raw_text_bn or self.raw_text_en or self.voice_audio_url):
            raise ValidationError(
                "At least one of raw_text_bn, raw_text_en, or voice_audio_url must be provided."
            )

    def save(self, *args, **kwargs):
        if not self.tracking_code:
            year = timezone.now().year
            div_prefix = self._derive_division_prefix()
            seq = secrets.randbelow(9_000_000) + 1_000_000
            self.tracking_code = f"BD-{year}-{div_prefix}-{seq:07d}"
        super().save(*args, **kwargs)

    def _derive_division_prefix(self) -> str:
        bbs_division_map = {
            "10": "BAR",
            "20": "CTG",
            "30": "DHK",
            "40": "KHL",
            "45": "MYM",
            "50": "RAJ",
            "55": "RNG",
            "60": "SYL",
        }
        return bbs_division_map.get((self.admin_geo_code or "")[:2], "NAT")

    def __str__(self) -> str:
        return f"{self.tracking_code} [{self.urgency_tier} | {self.status}]"


class TicketAssignment(models.Model):
    """Routes a complaint to a specific Doptor office, organogram seat, and officer."""

    assignment_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="assignments"
    )
    doptor_office_id = models.CharField(max_length=64, db_index=True)
    doptor_seat_id = models.CharField(max_length=64, db_index=True)
    assigned_officer_id = models.CharField(max_length=64, blank=True, db_index=True)
    role_level = models.CharField(max_length=16, choices=RoleLevel.choices, db_index=True)
    assigned_at = models.DateTimeField(auto_now_add=True, db_index=True)
    due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        db_table = "complaints_ticket_assignment"
        ordering = ["-assigned_at"]
        constraints = [
            UniqueConstraint(
                fields=["complaint", "role_level"],
                condition=Q(is_active=True),
                name="uq_active_assignment_per_role",
            ),
        ]
        indexes = [
            models.Index(
                fields=["doptor_seat_id", "is_active", "due_at"],
                name="idx_assign_seat_inbox",
            ),
            models.Index(
                fields=["doptor_office_id", "role_level", "is_active"],
                name="idx_assign_office_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.complaint.tracking_code} -> {self.doptor_seat_id} ({self.role_level})"


class ResolutionReport(models.Model):
    """Field resolution evidence with GPS distance verification and citizen verdict."""

    class CitizenVerdict(models.TextChoices):
        PENDING = "PENDING", "Pending Citizen Verification"
        ACCEPTED = "ACCEPTED", "Accepted by Citizen"
        REJECTED = "REJECTED", "Rejected by Citizen"

    report_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="resolution_reports"
    )
    submitted_by_seat = models.CharField(max_length=64, db_index=True)
    work_summary = models.TextField()
    after_photo_urls = models.JSONField(default=list, blank=True)
    gps_verified_dist_m = models.FloatField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0)],
        help_text="Geodesic distance in meters between complaint geo_point and after-photo EXIF/GPS.",
    )
    citizen_verdict = models.CharField(
        max_length=16,
        choices=CitizenVerdict.choices,
        default=CitizenVerdict.PENDING,
        db_index=True,
    )
    citizen_feedback = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "complaints_resolution_report"
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(
                fields=["complaint", "citizen_verdict"],
                name="idx_resrep_cmp_verdict",
            ),
        ]

    def __str__(self) -> str:
        return f"Report {self.report_id} for {self.complaint.tracking_code} [{self.citizen_verdict}]"


class AuditLogQuerySet(models.QuerySet):
    """Prevents bulk ORM mutations or deletions against the immutable ledger."""

    def update(self, **kwargs):
        raise AuditLogImmutabilityError("AuditLog entries are immutable and cannot be updated.")

    def delete(self):
        raise AuditLogImmutabilityError("AuditLog entries are immutable and cannot be deleted.")


class AuditLogManager(models.Manager.from_queryset(AuditLogQuerySet)):
    pass


class AuditLog(models.Model):
    """
    Immutable, append-only cryptographic ledger using SHA-256 hash chaining.
    Every new row locks the chain tail inside a transaction, links to previous_hash,
    and rejects any subsequent update or delete at both model and QuerySet layers.
    """

    GENESIS_HASH = "0" * 64

    log_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    sequence_no = models.BigIntegerField(unique=True, editable=False, db_index=True)
    complaint = models.ForeignKey(
        Complaint,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="audit_logs",
    )
    actor_id = models.CharField(max_length=64, db_index=True)
    actor_seat_id = models.CharField(max_length=64, blank=True, db_index=True)
    actor_role = models.CharField(max_length=32, blank=True)
    action = models.CharField(max_length=64, db_index=True)
    entity_type = models.CharField(max_length=64, default="Complaint")
    entity_id = models.CharField(max_length=64, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True)

    previous_hash = models.CharField(max_length=64, editable=False)
    current_hash = models.CharField(max_length=64, unique=True, editable=False, db_index=True)

    objects = AuditLogManager()

    class Meta:
        db_table = "complaints_audit_log"
        ordering = ["sequence_no"]
        default_permissions = ("add", "view")
        indexes = [
            models.Index(fields=["complaint", "sequence_no"], name="idx_audit_cmp_seq"),
            models.Index(fields=["action", "created_at"], name="idx_audit_action_ts"),
        ]

    def compute_hash(self) -> str:
        """Compute deterministic SHA-256 digest over canonical ledger fields."""
        canonical_payload = json.dumps(
            self.payload or {},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        material = "|".join(
            [
                str(self.sequence_no),
                self.previous_hash,
                str(self.complaint_id or ""),
                self.actor_id,
                self.actor_seat_id,
                self.actor_role,
                self.action,
                self.entity_type,
                self.entity_id,
                self.created_at.isoformat(),
                canonical_payload,
            ]
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AuditLogImmutabilityError(
                "AuditLog entries are append-only and cannot be modified after creation."
            )
        if kwargs.get("force_update"):
            raise AuditLogImmutabilityError("force_update is forbidden on AuditLog.")

        with transaction.atomic():
            if AuditLog.objects.filter(pk=self.pk).exists():
                raise AuditLogImmutabilityError(
                    "AuditLog entry with this log_id already exists and cannot be overwritten."
                )
            last_entry = (
                AuditLog.objects.select_for_update()
                .order_by("-sequence_no")
                .first()
            )
            self.sequence_no = (last_entry.sequence_no + 1) if last_entry else 1
            self.previous_hash = last_entry.current_hash if last_entry else self.GENESIS_HASH
            if self.created_at is None:
                self.created_at = timezone.now()
            self.current_hash = self.compute_hash()
            kwargs["force_insert"] = True
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutabilityError("AuditLog entries are immutable and cannot be deleted.")

    @classmethod
    def verify_chain(cls) -> tuple[bool, int, str | None]:
        """
        Walk the entire ledger in sequence order and verify every SHA-256 link.
        Returns (is_valid, checked_count, first_broken_log_id).
        """
        expected_prev = cls.GENESIS_HASH
        checked = 0
        for entry in cls.objects.order_by("sequence_no").iterator(chunk_size=1000):
            checked += 1
            if entry.previous_hash != expected_prev:
                return False, checked, str(entry.log_id)
            if entry.compute_hash() != entry.current_hash:
                return False, checked, str(entry.log_id)
            expected_prev = entry.current_hash
        return True, checked, None

    def __str__(self) -> str:
        return f"#{self.sequence_no} {self.action} ({self.current_hash[:12]}...)"


class ComplaintProgressUpdate(models.Model):
    """FR07: Timestamped officer interim progress reports visible on the citizen timeline."""

    update_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    complaint = models.ForeignKey(
        Complaint, on_delete=models.CASCADE, related_name="progress_updates"
    )
    officer_seat_id = models.CharField(max_length=64, blank=True, db_index=True)
    officer_name = models.CharField(max_length=150, blank=True)
    message = models.TextField()
    attachment_url = models.URLField(max_length=1024, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "complaints_progress_update"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"ProgressUpdate({self.complaint_id}, {self.officer_seat_id})"


class CitizenNotification(models.Model):
    """FR09: Multi-channel (SMS, Push, In-App) citizen notification ledger."""

    class Channel(models.TextChoices):
        IN_APP = "IN_APP", "In-App Alert"
        SMS = "SMS", "SMS Dispatch"
        PUSH = "PUSH", "Web/Mobile Push"

    class EventType(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Grievance Submitted"
        ASSIGNED = "ASSIGNED", "Assigned to Officer/Field"
        PROGRESS_UPDATE = "PROGRESS_UPDATE", "Officer Progress Update"
        PENDING_VERIFY = "PENDING_VERIFY", "Pending Citizen Two-Key Verification"
        ESCALATED = "ESCALATED", "Escalated / Reopened"
        CLOSED = "CLOSED", "Resolved & Closed"

    notification_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="citizen_notifications",
    )
    citizen_uct_hash = models.CharField(max_length=64, blank=True, db_index=True)
    complaint = models.ForeignKey(
        Complaint,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    channel = models.CharField(
        max_length=16, choices=Channel.choices, default=Channel.IN_APP, db_index=True
    )
    event_type = models.CharField(
        max_length=24, choices=EventType.choices, default=EventType.SUBMITTED, db_index=True
    )
    title = models.CharField(max_length=200)
    message = models.TextField()
    sms_dispatch_status = models.CharField(max_length=32, default="SIMULATED_SENT")
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "complaints_citizen_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_read", "created_at"], name="idx_notif_unread_created"),
        ]

    @classmethod
    def dispatch_event(
        cls,
        *,
        complaint: Complaint | None,
        event_type: str,
        title: str,
        message: str,
        user=None,
        channels: tuple[str, ...] = ("IN_APP", "SMS", "PUSH"),
    ) -> list["CitizenNotification"]:
        uct_hash = complaint.citizen_uct_hash if complaint else ""
        created: list[CitizenNotification] = []
        for ch in channels:
            sms_status = "DISPATCHED_SMS_GW" if ch == cls.Channel.SMS else "DELIVERED"
            created.append(
                cls.objects.create(
                    user=user if (user and getattr(user, "is_authenticated", False)) else None,
                    citizen_uct_hash=uct_hash,
                    complaint=complaint,
                    channel=ch,
                    event_type=event_type,
                    title=title[:200],
                    message=message,
                    sms_dispatch_status=sms_status,
                )
            )
        return created

    def __str__(self) -> str:
        return f"[{self.channel}] {self.title}"
