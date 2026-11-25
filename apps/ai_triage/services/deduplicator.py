"""
Geo-Spatial Deduplication & Hotspot Clustering via PostGIS ST_DWithin (200m radius).

Clusters duplicate complaints matching `ai_category_code` within 200m into a single
Master Incident, subscribes all unique citizens to live updates, and dynamically
boosts priority (P4 -> P3 -> P2 -> P1) based on unique citizen count.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.gis.measure import D
from django.db import transaction
from django.utils import timezone

from apps.ai_triage.models import MasterIncidentSubscription
from apps.complaints.models import AuditLog, Complaint


@dataclass(frozen=True)
class DeduplicationResult:
    is_duplicate: bool
    master_incident: Complaint
    unique_citizen_count: int
    priority_boosted_to: str | None = None


class SpatialDeduplicationService:
    """PostGIS ST_DWithin (200m) spatial deduplicator with dynamic hotspot priority boost."""

    OPEN_CLUSTER_STATUSES = (
        Complaint.ComplaintStatus.SUBMITTED,
        Complaint.ComplaintStatus.ROUTED,
        Complaint.ComplaintStatus.IN_PROGRESS,
        Complaint.ComplaintStatus.TRANSFERRED,
        Complaint.ComplaintStatus.ARBITRATION_LOCKED,
    )
    CLUSTER_LOOKBACK_HOURS = 72
    P2_BOOST_CITIZEN_THRESHOLD = 3
    P1_BOOST_CITIZEN_THRESHOLD = 10

    @classmethod
    @transaction.atomic
    def deduplicate_and_cluster(
        cls,
        *,
        complaint: Complaint,
        radius_m: float | None = None,
        actor_id: str = "SYSTEM-SPATIAL-DEDUP",
    ) -> DeduplicationResult:
        if complaint.geo_point is None or not complaint.ai_category_code:
            return DeduplicationResult(
                is_duplicate=False,
                master_incident=complaint,
                unique_citizen_count=1,
            )

        effective_radius = float(
            radius_m if radius_m is not None else getattr(settings, "DEDUP_RADIUS_METERS", 200.0)
        )
        lookback_cutoff = timezone.now() - timedelta(hours=cls.CLUSTER_LOOKBACK_HOURS)

        master = (
            Complaint.objects.filter(
                ai_category_code=complaint.ai_category_code,
                status__in=cls.OPEN_CLUSTER_STATUSES,
                master_cluster__isnull=True,
                created_at__gte=lookback_cutoff,
                geo_point__dwithin=(complaint.geo_point, D(m=effective_radius)),
            )
            .exclude(pk=complaint.pk)
            .order_by("created_at")
            .first()
        )

        if master is None:
            MasterIncidentSubscription.objects.get_or_create(
                master_complaint=complaint,
                citizen_uct_hash=complaint.citizen_uct_hash,
                defaults={"duplicate_complaint": None},
            )
            return DeduplicationResult(
                is_duplicate=False,
                master_incident=complaint,
                unique_citizen_count=1,
            )

        # Ensure master's original citizen is subscribed, then subscribe the duplicate's citizen
        MasterIncidentSubscription.objects.get_or_create(
            master_complaint=master,
            citizen_uct_hash=master.citizen_uct_hash,
            defaults={"duplicate_complaint": None},
        )
        MasterIncidentSubscription.objects.get_or_create(
            master_complaint=master,
            citizen_uct_hash=complaint.citizen_uct_hash,
            defaults={"duplicate_complaint": complaint},
        )

        complaint.master_cluster = master
        complaint.status = Complaint.ComplaintStatus.MERGED_DUPLICATE
        complaint.save(update_fields=["master_cluster", "status", "updated_at"])

        unique_count = MasterIncidentSubscription.objects.filter(
            master_complaint=master
        ).count()

        boosted_tier = cls._maybe_boost_priority(master, unique_count)

        AuditLog.objects.create(
            complaint=master,
            actor_id=actor_id,
            actor_role="SYSTEM",
            action="SPATIAL_DUPLICATE_CLUSTERED",
            entity_type="Complaint",
            entity_id=str(complaint.complaint_id),
            payload={
                "master_tracking_code": master.tracking_code,
                "duplicate_tracking_code": complaint.tracking_code,
                "radius_m": effective_radius,
                "unique_citizen_count": unique_count,
                "priority_boosted_to": boosted_tier,
            },
        )
        return DeduplicationResult(
            is_duplicate=True,
            master_incident=master,
            unique_citizen_count=unique_count,
            priority_boosted_to=boosted_tier,
        )

    @classmethod
    def _maybe_boost_priority(cls, master: Complaint, unique_citizen_count: int) -> str | None:
        rank = {
            Complaint.UrgencyTier.P4: 4,
            Complaint.UrgencyTier.P3: 3,
            Complaint.UrgencyTier.P2: 2,
            Complaint.UrgencyTier.P1: 1,
        }
        current_rank = rank.get(master.urgency_tier, 3)
        target_tier = None

        if unique_citizen_count >= cls.P1_BOOST_CITIZEN_THRESHOLD and current_rank > 1:
            target_tier = Complaint.UrgencyTier.P1
        elif unique_citizen_count >= cls.P2_BOOST_CITIZEN_THRESHOLD and current_rank > 2:
            target_tier = Complaint.UrgencyTier.P2

        if target_tier:
            master.urgency_tier = target_tier
            master.save(update_fields=["urgency_tier", "updated_at"])
        return target_tier
