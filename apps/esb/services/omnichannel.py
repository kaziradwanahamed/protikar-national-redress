"""
Omnichannel Intake Parsers:
  - WhatsApp & Facebook Messenger Bot Webhooks (text, voice note, photo, GPS pin)
  - <140-Byte SMS / USSD Degraded-Mode 2G Disaster Parser with automatic P1 Fast-Lane routing
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from django.contrib.gis.geos import Point
from django.db import transaction

from apps.complaints.models import Complaint
from apps.disaster.services.h3_surge_pipeline import (
    H3SurgeIngestionService,
    detect_life_safety_keywords,
    latlng_to_h3_res8,
)
from apps.esb.models import OmnichannelIntakeRecord


MAX_2G_SMS_BYTES = 140


class CompactSMSParseError(ValueError):
    """Raised when a 2G SMS/USSD payload exceeds 140 bytes or lacks required fields."""


@dataclass(frozen=True)
class Compact2GMessage:
    urgency_tier: str
    lat: float | None
    lon: float | None
    bbs_geo_code: str
    agency_hint: str
    message: str
    byte_length: int


def parse_compact_2g_payload(raw_text: str) -> Compact2GMessage:
    """
    Parse <140-byte SMS or USSD 2G disaster fallback messages.
    Supported compact grammars:
      1) SMS:  `SOS#P1#23.7925,90.4143#Trapped on roof`
      2) USSD: `USSD*1*302626*WASA*Pipe burst`
      3) Plain short Bangla/English SMS <= 140 bytes
    """
    raw = (raw_text or "").strip()
    byte_len = len(raw.encode("utf-8"))
    if byte_len == 0:
        raise CompactSMSParseError("Empty 2G SMS/USSD payload.")
    if byte_len > MAX_2G_SMS_BYTES:
        raise CompactSMSParseError(
            f"Degraded-mode 2G payload is {byte_len} bytes (maximum allowed is {MAX_2G_SMS_BYTES} bytes)."
        )

    urgency = Complaint.UrgencyTier.P3
    lat, lon = None, None
    bbs_code = ""
    agency_hint = ""
    msg = raw

    if "#" in raw:
        parts = [p.strip() for p in raw.split("#")]
        if parts[0].upper() in ("SOS", "P1"):
            urgency = Complaint.UrgencyTier.P1
        if len(parts) >= 2 and parts[1].upper() in ("P1", "P2", "P3", "P4"):
            urgency = parts[1].upper()
        if len(parts) >= 3 and "," in parts[2]:
            lat_s, lon_s = parts[2].split(",", 1)
            lat, lon = float(lat_s.strip()), float(lon_s.strip())
        elif len(parts) >= 3 and parts[2].isdigit():
            bbs_code = parts[2]
        if len(parts) >= 4:
            msg = parts[3]
    elif raw.upper().startswith("USSD*") or "*" in raw:
        parts = [p.strip() for p in raw.split("*")]
        # USSD*<prio_num>*<bbs_code>*<agency>*<short_msg>
        prio_map = {"1": "P1", "2": "P2", "3": "P3", "4": "P4"}
        if len(parts) >= 2:
            urgency = prio_map.get(parts[1], "P3")
        if len(parts) >= 3 and parts[2].isdigit():
            bbs_code = parts[2]
        if len(parts) >= 4:
            agency_hint = parts[3].upper()
        if len(parts) >= 5:
            msg = parts[4]

    if detect_life_safety_keywords(msg):
        urgency = Complaint.UrgencyTier.P1

    return Compact2GMessage(
        urgency_tier=urgency,
        lat=lat,
        lon=lon,
        bbs_geo_code=bbs_code,
        agency_hint=agency_hint,
        message=msg,
        byte_length=byte_len,
    )


class OmnichannelIntakeService:
    """Ingests WhatsApp, Messenger, and <140-byte 2G SMS/USSD submissions."""

    @staticmethod
    def _hash_sender(sender_id: str) -> str:
        return hashlib.sha256(f"omni:{sender_id}".encode("utf-8")).hexdigest()

    @classmethod
    @transaction.atomic
    def ingest_compact_2g(
        cls, *, sender_phone: str, raw_payload: str, channel: str = OmnichannelIntakeRecord.Channel.SMS_2G
    ) -> dict[str, Any]:
        parsed = parse_compact_2g_payload(raw_payload)
        point = (
            Point(parsed.lon, parsed.lat, srid=4326)
            if (parsed.lat is not None and parsed.lon is not None)
            else None
        )
        h3_idx = latlng_to_h3_res8(parsed.lat, parsed.lon) if point else ""

        complaint = Complaint.objects.create(
            citizen_uct_hash=cls._hash_sender(sender_phone),
            raw_text_en=parsed.message,
            urgency_tier=parsed.urgency_tier,
            geo_point=point,
            admin_geo_code=parsed.bbs_geo_code,
            h3_hex_index=h3_idx,
            status=Complaint.ComplaintStatus.SUBMITTED,
        )

        fastlane_triggered = False
        dispatch_id = None
        if parsed.urgency_tier == Complaint.UrgencyTier.P1 or detect_life_safety_keywords(parsed.message):
            surge_res = H3SurgeIngestionService.ingest_surge_report(
                lat=parsed.lat if parsed.lat is not None else 23.8103,
                lon=parsed.lon if parsed.lon is not None else 90.4125,
                message=parsed.message,
                citizen_phone=sender_phone,
                complaint=complaint,
            )
            fastlane_triggered = surge_res.fastlane_triggered
            dispatch_id = surge_res.dispatch_id

        intake = OmnichannelIntakeRecord.objects.create(
            channel=channel,
            sender_id=sender_phone,
            raw_payload=raw_payload,
            byte_length=parsed.byte_length,
            parsed_fields={
                "urgency_tier": parsed.urgency_tier,
                "lat": parsed.lat,
                "lon": parsed.lon,
                "bbs_geo_code": parsed.bbs_geo_code,
                "agency_hint": parsed.agency_hint,
                "message": parsed.message,
            },
            complaint_id=complaint.complaint_id,
            crisis_fastlane_triggered=fastlane_triggered,
        )

        # Compact <140-byte 2G SMS confirmation reply
        sms_reply = f"OK:{complaint.tracking_code}|{complaint.urgency_tier}|{'999-SENT' if fastlane_triggered else 'LOGGED'}"
        return {
            "intake_id": str(intake.intake_id),
            "complaint_id": str(complaint.complaint_id),
            "tracking_code": complaint.tracking_code,
            "byte_length": parsed.byte_length,
            "fastlane_triggered": fastlane_triggered,
            "dispatch_id": dispatch_id,
            "sms_reply": sms_reply[:140],
        }

    @classmethod
    @transaction.atomic
    def ingest_social_bot(
        cls,
        *,
        channel: str,
        sender_id: str,
        text: str = "",
        voice_audio_url: str = "",
        lat: float | None = None,
        lon: float | None = None,
    ) -> dict[str, Any]:
        point = Point(lon, lat, srid=4326) if (lat is not None and lon is not None) else None
        h3_idx = latlng_to_h3_res8(lat, lon) if point else ""
        complaint = Complaint.objects.create(
            citizen_uct_hash=cls._hash_sender(f"{channel}:{sender_id}"),
            raw_text_en=text,
            voice_audio_url=voice_audio_url,
            geo_point=point,
            h3_hex_index=h3_idx,
            status=Complaint.ComplaintStatus.SUBMITTED,
        )
        intake = OmnichannelIntakeRecord.objects.create(
            channel=channel,
            sender_id=sender_id,
            raw_payload=text or voice_audio_url,
            byte_length=len((text or voice_audio_url).encode("utf-8")),
            parsed_fields={"lat": lat, "lon": lon, "voice_audio_url": voice_audio_url},
            complaint_id=complaint.complaint_id,
        )
        return {
            "intake_id": str(intake.intake_id),
            "complaint_id": str(complaint.complaint_id),
            "tracking_code": complaint.tracking_code,
        }
