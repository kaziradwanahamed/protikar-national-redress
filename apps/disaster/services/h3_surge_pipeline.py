"""
Disaster Surge Ingestion Pipeline:
  - Async Apache Kafka publishing (no PostgreSQL write lock under cyclone/flood spikes)
  - O(1) Uber H3 Hexagonal Indexing (Resolution 8) into Redis Macro-Incident Counters & Heatmaps
  - P1 Life-Safety Fast-Lane filtering acute rescue keywords to 999, Fire Service,
    Armed Forces Disaster Cells, and CPP volunteers.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.contrib.gis.geos import Point
from django.utils import timezone

from apps.disaster.models import CrisisZone, EmergencyCommandDispatch
from apps.disaster.services.circuit_breaker import _get_redis_client

logger = logging.getLogger(__name__)

# In-memory fallback for Redis H3 heatmap counters during isolated tests
_MEMORY_H3_HEATMAP: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

LIFE_SAFETY_RESCUE_KEYWORDS: tuple[str, ...] = (
    "trapped on roof",
    "ছাদে আটকা",
    "medical emergency",
    "জরুরি চিকিৎসা",
    "embankment breach",
    "বাঁধ ভেঙে",
    "live wire in water",
    "পানিতে বিদ্যুতের তার",
    "drowning",
    "ডুবে যাচ্ছি",
    "collapsed building",
    "ভবন ধসে",
    "fire trapped",
    "আগুনে আটকা",
)

FASTLANE_RESPONDERS: list[str] = [
    "999_NATIONAL_EMERGENCY",
    "FIRE_SERVICE_CIVIL_DEFENCE",
    "ARMED_FORCES_DISASTER_CELL",
    "CPP_CYCLONE_VOLUNTEERS",
]


def latlng_to_h3_res8(lat: float, lon: float, resolution: int | None = None) -> str:
    """O(1) conversion from WGS84 (lat, lon) to Uber H3 Resolution 8 hex index."""
    res = int(resolution if resolution is not None else getattr(settings, "DISASTER_H3_RESOLUTION", 8))
    try:
        import h3

        if hasattr(h3, "latlng_to_cell"):
            return str(h3.latlng_to_cell(float(lat), float(lon), res))
        return str(h3.geo_to_h3(float(lat), float(lon), res))
    except ImportError:
        # Deterministic O(1) ~0.7km hex-equivalent cell ID fallback when C-ext h3 is absent
        lat_bin = int(round((float(lat) + 90.0) * 150))
        lon_bin = int(round((float(lon) + 180.0) * 150))
        return f"8{res}bd{lat_bin:05x}{lon_bin:05x}"


def detect_life_safety_keywords(message: str) -> list[str]:
    lower = (message or "").lower()
    return [kw for kw in LIFE_SAFETY_RESCUE_KEYWORDS if kw in lower]


@dataclass(frozen=True)
class SurgeIngestResult:
    h3_res8_index: str
    hex_counter_value: int
    kafka_topic: str
    fastlane_triggered: bool
    matched_rescue_keywords: list[str] = field(default_factory=list)
    dispatch_id: str | None = None


class H3SurgeIngestionService:
    """Ingests high-volume disaster reports via Kafka + Redis H3 Res-8 counters + P1 Fast-Lane."""

    @staticmethod
    def _publish_kafka(topic: str, key: str, payload: dict[str, Any]) -> bool:
        if getattr(settings, "KAFKA_PROVIDER_MODE", "mock").lower() != "production":
            return True
        try:
            from confluent_kafka import Producer

            producer = Producer({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS})
            producer.produce(
                topic=topic,
                key=key.encode("utf-8"),
                value=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            producer.flush(timeout=2.0)
            return True
        except Exception as exc:
            logger.warning("Kafka publish deferred for topic %s: %s", topic, exc)
            return False

    @classmethod
    def ingest_surge_report(
        cls,
        *,
        lat: float,
        lon: float,
        message: str,
        citizen_phone: str = "",
        crisis_zone: CrisisZone | None = None,
        complaint=None,
    ) -> SurgeIngestResult:
        h3_index = latlng_to_h3_res8(lat, lon)
        zone_key = str(crisis_zone.crisis_id) if crisis_zone else "NATIONAL"

        # 1. O(1) Redis Macro-Incident Counter & Heatmap update (zero PostgreSQL lock)
        client = _get_redis_client()
        if client is not None:
            pipe = client.pipeline()
            pipe.hincrby(f"crisis:{zone_key}:h3_res8", h3_index, 1)
            pipe.zincrby(f"crisis:{zone_key}:hotspots", 1, h3_index)
            hex_count = int(pipe.execute()[0])
        else:
            _MEMORY_H3_HEATMAP[zone_key][h3_index] += 1
            hex_count = _MEMORY_H3_HEATMAP[zone_key][h3_index]

        topic_prefix = getattr(settings, "KAFKA_TOPIC_PREFIX", "bd.grievance")
        surge_topic = f"{topic_prefix}.disaster.surge"
        cls._publish_kafka(
            topic=surge_topic,
            key=h3_index,
            payload={
                "crisis_zone_id": zone_key,
                "h3_res8_index": h3_index,
                "lat": lat,
                "lon": lon,
                "message": message,
                "timestamp": timezone.now().isoformat(),
            },
        )

        # 2. P1 Life-Safety Fast-Lane detection
        matched_keywords = detect_life_safety_keywords(message)
        dispatch_id = None
        if matched_keywords:
            fastlane_topic = f"{topic_prefix}.emergency.fastlane"
            dispatch = EmergencyCommandDispatch.objects.create(
                crisis_zone=crisis_zone,
                complaint=complaint,
                citizen_phone=citizen_phone,
                raw_message=message,
                matched_rescue_keywords=matched_keywords,
                geo_point=Point(float(lon), float(lat), srid=4326),
                h3_res8_index=h3_index,
                target_responders=FASTLANE_RESPONDERS,
                kafka_topic=fastlane_topic,
                status=EmergencyCommandDispatch.DispatchStatus.STREAMED,
            )
            dispatch_id = str(dispatch.dispatch_id)
            cls._publish_kafka(
                topic=fastlane_topic,
                key=h3_index,
                payload={
                    "dispatch_id": dispatch_id,
                    "responders": FASTLANE_RESPONDERS,
                    "matched_keywords": matched_keywords,
                    "lat": lat,
                    "lon": lon,
                    "citizen_phone": citizen_phone,
                    "raw_message": message,
                },
            )

        return SurgeIngestResult(
            h3_res8_index=h3_index,
            hex_counter_value=hex_count,
            kafka_topic=surge_topic,
            fastlane_triggered=bool(matched_keywords),
            matched_rescue_keywords=matched_keywords,
            dispatch_id=dispatch_id,
        )

    @classmethod
    def get_live_h3_heatmap(cls, crisis_id: str = "NATIONAL", top_n: int = 100) -> list[dict[str, Any]]:
        """Read live H3 Res-8 macro-incident heatmap directly from Redis without hitting PostgreSQL."""
        client = _get_redis_client()
        if client is not None:
            rows = client.zrevrange(f"crisis:{crisis_id}:hotspots", 0, top_n - 1, withscores=True)
            return [
                {"h3_res8_index": cell.decode("utf-8"), "incident_count": int(score)}
                for cell, score in rows
            ]
        bucket = _MEMORY_H3_HEATMAP.get(crisis_id, {})
        ordered = sorted(bucket.items(), key=lambda kv: kv[1], reverse=True)[:top_n]
        return [{"h3_res8_index": cell, "incident_count": count} for cell, count in ordered]
