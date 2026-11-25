"""
Disaster Crisis Mode Circuit Breaker & Routine P3/P4 SLA Freeze Service.

Monitors rolling 1-hour complaint velocity per geographic polygon in Redis.
If velocity exceeds 5x rolling baseline (or MoDMR/DC triggers manual toggle),
activates Crisis Mode and automatically suspends routine P3/P4 SLAs inside the polygon.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.complaints.models import AuditLog, Complaint
from apps.disaster.models import CrisisZone
from apps.organogram.models import ServiceAreaPolygon
from apps.workflow.models import WorkflowTracker

logger = logging.getLogger(__name__)


class _InMemoryVelocityStore:
    """Thread-local / unit-test fallback when Redis is unreachable."""

    def __init__(self):
        self._events: dict[str, list[float]] = defaultdict(list)

    def record_and_count(self, key: str, window_seconds: int = 3600) -> int:
        now = time.time()
        cutoff = now - window_seconds
        bucket = [ts for ts in self._events[key] if ts >= cutoff]
        bucket.append(now)
        self._events[key] = bucket
        return len(bucket)


_MEMORY_VELOCITY = _InMemoryVelocityStore()


def _get_redis_client():
    try:
        import redis

        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1.0)
        client.ping()
        return client
    except Exception:
        return None


class DisasterCircuitBreakerService:
    """Monitors per-polygon surge velocity and manages CrisisZone activation & P3/P4 SLA freeze."""

    FREEZE_ELIGIBLE_TIERS = (Complaint.UrgencyTier.P3, Complaint.UrgencyTier.P4)
    FREEZE_ELIGIBLE_STATUSES = (
        Complaint.ComplaintStatus.SUBMITTED,
        Complaint.ComplaintStatus.ROUTED,
        Complaint.ComplaintStatus.TRANSFERRED,
        Complaint.ComplaintStatus.IN_PROGRESS,
    )

    @classmethod
    def record_polygon_hit(
        cls,
        *,
        zone_code: str,
        baseline_per_hour: float = 10.0,
        window_seconds: int = 3600,
    ) -> dict:
        redis_key = f"disaster:velocity:{zone_code}"
        multiplier = float(getattr(settings, "DISASTER_SURGE_MULTIPLIER", 5.0))
        client = _get_redis_client()

        if client is not None:
            now_ts = time.time()
            pipe = client.pipeline()
            pipe.zadd(redis_key, {f"{now_ts}-{time.monotonic_ns()}": now_ts})
            pipe.zremrangebyscore(redis_key, 0, now_ts - window_seconds)
            pipe.zcard(redis_key)
            pipe.expire(redis_key, window_seconds + 60)
            results = pipe.execute()
            current_rate = int(results[2])
        else:
            current_rate = _MEMORY_VELOCITY.record_and_count(redis_key, window_seconds)

        threshold = baseline_per_hour * multiplier
        tripped = current_rate > threshold

        activated_zone = None
        if tripped:
            polygon = ServiceAreaPolygon.objects.filter(zone_code=zone_code, is_active=True).first()
            if polygon:
                activated_zone = cls.activate_crisis_zone(
                    crisis_code=f"AUTO-{zone_code}-{timezone.now().strftime('%Y%m%d')}",
                    name_en=f"Auto Surge Crisis — {polygon.name_en}",
                    name_bn=polygon.name_bn,
                    disaster_type=CrisisZone.DisasterType.FLOOD,
                    trigger_source=CrisisZone.TriggerSource.AUTO_5X_VELOCITY,
                    geom=polygon.geom,
                    affected_area_polygon=polygon,
                    baseline_rate_per_hour=baseline_per_hour,
                    peak_rate_per_hour=float(current_rate),
                    activated_by_seat="SYSTEM-CIRCUIT-BREAKER",
                )

        return {
            "zone_code": zone_code,
            "current_rate_per_hour": current_rate,
            "threshold_5x": threshold,
            "circuit_breaker_tripped": tripped,
            "crisis_id": str(activated_zone.crisis_id) if activated_zone else None,
        }

    @classmethod
    @transaction.atomic
    def activate_crisis_zone(
        cls,
        *,
        crisis_code: str,
        name_en: str,
        geom,
        trigger_source: str,
        disaster_type: str = CrisisZone.DisasterType.FLOOD,
        name_bn: str = "",
        affected_area_polygon: ServiceAreaPolygon | None = None,
        baseline_rate_per_hour: float = 10.0,
        peak_rate_per_hour: float = 0.0,
        activated_by_seat: str = "",
    ) -> CrisisZone:
        zone, _ = CrisisZone.objects.update_or_create(
            crisis_code=crisis_code,
            defaults={
                "name_en": name_en,
                "name_bn": name_bn,
                "disaster_type": disaster_type,
                "trigger_source": trigger_source,
                "affected_area_polygon": affected_area_polygon,
                "geom": geom,
                "baseline_rate_per_hour": baseline_rate_per_hour,
                "peak_rate_per_hour": peak_rate_per_hour,
                "is_active": True,
                "activated_by_seat": activated_by_seat,
                "deactivated_at": None,
            },
        )
        frozen_count = cls.freeze_routine_sla_in_zone(zone)
        zone.frozen_ticket_count = frozen_count
        zone.save(update_fields=["frozen_ticket_count"])

        AuditLog.objects.create(
            actor_id=activated_by_seat or "SYSTEM-CIRCUIT-BREAKER",
            actor_seat_id=activated_by_seat,
            actor_role="SYSTEM",
            action="DISASTER_CRISIS_MODE_ACTIVATED",
            entity_type="CrisisZone",
            entity_id=str(zone.crisis_id),
            payload={
                "crisis_code": zone.crisis_code,
                "trigger_source": trigger_source,
                "frozen_p3_p4_tickets": frozen_count,
            },
        )
        return zone

    @classmethod
    @transaction.atomic
    def freeze_routine_sla_in_zone(cls, crisis_zone: CrisisZone) -> int:
        """Suspend active P3/P4 tickets inside the disaster polygon to DISASTER_SLA_SUSPENDED."""
        now = timezone.now()
        affected = Complaint.objects.filter(
            urgency_tier__in=cls.FREEZE_ELIGIBLE_TIERS,
            status__in=cls.FREEZE_ELIGIBLE_STATUSES,
            geo_point__within=crisis_zone.geom,
        )
        frozen = 0
        for complaint in affected:
            complaint.status = Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED
            complaint.crisis_zone_id = crisis_zone.crisis_id
            complaint.hold_reason_code = Complaint.HoldReasonCode.DISASTER_FREEZE
            complaint.hold_reference_id = crisis_zone.crisis_code
            complaint.save(
                update_fields=[
                    "status",
                    "crisis_zone_id",
                    "hold_reason_code",
                    "hold_reference_id",
                    "updated_at",
                ]
            )
            tracker = WorkflowTracker.objects.filter(complaint=complaint).first()
            if tracker and tracker.sla_paused_at is None:
                tracker.sla_paused_at = now
                tracker.save(update_fields=["sla_paused_at", "updated_at"])
            frozen += 1
        return frozen

    @classmethod
    @transaction.atomic
    def deactivate_crisis_zone(cls, *, crisis_zone: CrisisZone, actor_seat_id: str) -> int:
        """Deactivate Crisis Mode and resume SLA clocks on suspended P3/P4 complaints."""
        now = timezone.now()
        crisis_zone.is_active = False
        crisis_zone.deactivated_at = now
        crisis_zone.save(update_fields=["is_active", "deactivated_at"])

        suspended = Complaint.objects.filter(
            crisis_zone_id=crisis_zone.crisis_id,
            status=Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED,
        )
        resumed = 0
        for complaint in suspended:
            tracker = WorkflowTracker.objects.filter(complaint=complaint).first()
            if tracker and tracker.sla_paused_at is not None:
                paused_sec = int(max(0.0, (now - tracker.sla_paused_at).total_seconds()))
                tracker.sla_accumulated_pause_seconds += paused_sec
                tracker.sla_paused_at = None
                tracker.save(
                    update_fields=["sla_accumulated_pause_seconds", "sla_paused_at", "updated_at"]
                )
                if complaint.sla_deadline_at:
                    complaint.sla_deadline_at = complaint.sla_deadline_at + timedelta(seconds=paused_sec)
            complaint.status = Complaint.ComplaintStatus.IN_PROGRESS
            complaint.save(update_fields=["status", "sla_deadline_at", "updated_at"])
            resumed += 1

        AuditLog.objects.create(
            actor_id=actor_seat_id or "MODMR-COMMAND",
            actor_seat_id=actor_seat_id,
            actor_role="APPELLATE",
            action="DISASTER_CRISIS_MODE_DEACTIVATED",
            entity_type="CrisisZone",
            entity_id=str(crisis_zone.crisis_id),
            payload={"resumed_tickets": resumed},
        )
        return resumed
