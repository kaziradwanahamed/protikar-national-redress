"""
Tier 1 National ESB: Canonical JSON Outbound Webhook Dispatcher & Signed Inbound Receiver
for GRS, D-Nothi, 999, DESCO/DPDC, WASA, BRTA, DNCC/DSCC.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.complaints.models import AuditLog, Complaint
from apps.esb.models import AgencyEndpoint, ESBDeliveryLog


TIER_1_SUPPORTED_AGENCIES = (
    "GRS",
    "D_NOTHI",
    "999",
    "DESCO",
    "DPDC",
    "WASA",
    "BRTA",
    "DNCC",
    "DSCC",
)


class WebhookSignatureError(PermissionError):
    """Raised when an inbound Tier-1 agency webhook fails HMAC-SHA256 verification."""


class Tier1WebhookService:
    """Signs, dispatches, and receives canonical JSON ESB webhooks across Tier-1 agencies."""

    @staticmethod
    def sign_payload(raw_bytes: bytes, secret: str) -> str:
        return hmac.new(secret.encode("utf-8"), raw_bytes, hashlib.sha256).hexdigest()

    @classmethod
    def verify_signature(cls, raw_bytes: bytes, signature: str, secret: str) -> bool:
        expected = cls.sign_payload(raw_bytes, secret)
        return hmac.compare_digest(expected, (signature or "").strip())

    @classmethod
    def build_canonical_envelope(
        cls,
        *,
        agency_code: str,
        event_type: str,
        complaint: Complaint,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "event_id": str(uuid.uuid4()),
            "agency_code": agency_code,
            "event_type": event_type,
            "timestamp": timezone.now().isoformat(),
            "complaint": {
                "complaint_id": str(complaint.complaint_id),
                "tracking_code": complaint.tracking_code,
                "urgency_tier": complaint.urgency_tier,
                "status": complaint.status,
                "ai_category_code": complaint.ai_category_code,
                "admin_geo_code": complaint.admin_geo_code,
                "geo_point": (
                    {"lon": complaint.geo_point.x, "lat": complaint.geo_point.y}
                    if complaint.geo_point
                    else None
                ),
                "sla_deadline_at": (
                    complaint.sla_deadline_at.isoformat() if complaint.sla_deadline_at else None
                ),
            },
            "extra": extra or {},
        }

    @classmethod
    @transaction.atomic
    def dispatch_outbound(
        cls,
        *,
        agency_code: str,
        event_type: str,
        complaint: Complaint,
        extra: dict[str, Any] | None = None,
    ) -> ESBDeliveryLog:
        endpoint = AgencyEndpoint.objects.filter(agency_code=agency_code, is_active=True).first()
        envelope = cls.build_canonical_envelope(
            agency_code=agency_code,
            event_type=event_type,
            complaint=complaint,
            extra=extra,
        )
        secret = (
            endpoint.hmac_secret
            if (endpoint and endpoint.hmac_secret)
            else getattr(settings, "ESB_WEBHOOK_SIGNING_SECRET", settings.SECRET_KEY)
        )
        raw_bytes = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
        signature = cls.sign_payload(raw_bytes, secret)

        http_status = 200
        delivery_status = ESBDeliveryLog.Status.DELIVERED

        if (
            getattr(settings, "ESB_PROVIDER_MODE", "mock").lower() == "production"
            and endpoint
            and endpoint.webhook_url
        ):
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(
                        endpoint.webhook_url,
                        content=raw_bytes,
                        headers={
                            "Content-Type": "application/json",
                            "X-BD-ESB-Signature": signature,
                            "X-BD-ESB-Agency": agency_code,
                        },
                    )
                    http_status = resp.status_code
                    delivery_status = (
                        ESBDeliveryLog.Status.DELIVERED
                        if 200 <= resp.status_code < 300
                        else ESBDeliveryLog.Status.FAILED
                    )
            except Exception:
                http_status = 503
                delivery_status = ESBDeliveryLog.Status.FAILED

        return ESBDeliveryLog.objects.create(
            agency_code=agency_code,
            direction=ESBDeliveryLog.Direction.OUTBOUND,
            event_type=event_type,
            complaint_id=complaint.complaint_id,
            idempotency_key=f"out:{agency_code}:{complaint.complaint_id}:{envelope['event_id']}",
            payload=envelope,
            http_status=http_status,
            status=delivery_status,
        )

    @classmethod
    @transaction.atomic
    def receive_inbound(
        cls,
        *,
        agency_code: str,
        raw_bytes: bytes,
        signature: str,
        payload: dict[str, Any],
    ) -> ESBDeliveryLog:
        endpoint = AgencyEndpoint.objects.filter(agency_code=agency_code, is_active=True).first()
        secret = (
            endpoint.hmac_secret
            if (endpoint and endpoint.hmac_secret)
            else getattr(settings, "ESB_WEBHOOK_SIGNING_SECRET", settings.SECRET_KEY)
        )
        if not cls.verify_signature(raw_bytes, signature, secret):
            raise WebhookSignatureError(f"Invalid HMAC-SHA256 signature for agency '{agency_code}'.")

        event_id = str(payload.get("event_id") or uuid.uuid4())
        event_type = str(payload.get("event_type") or "EXTERNAL_STATUS_UPDATE")
        tracking_code = payload.get("tracking_code", "")
        complaint = Complaint.objects.filter(tracking_code=tracking_code).first() if tracking_code else None

        log, _ = ESBDeliveryLog.objects.get_or_create(
            idempotency_key=f"in:{agency_code}:{event_id}",
            defaults={
                "agency_code": agency_code,
                "direction": ESBDeliveryLog.Direction.INBOUND,
                "event_type": event_type,
                "complaint_id": complaint.complaint_id if complaint else None,
                "payload": payload,
                "http_status": 200,
                "status": ESBDeliveryLog.Status.ACKNOWLEDGED,
            },
        )

        AuditLog.objects.create(
            complaint=complaint,
            actor_id=f"ESB-{agency_code}",
            actor_role="SYSTEM",
            action=f"ESB_INBOUND_{event_type}",
            entity_type="ESBDeliveryLog",
            entity_id=str(log.delivery_id),
            payload={"agency_code": agency_code, "tracking_code": tracking_code},
        )
        return log
