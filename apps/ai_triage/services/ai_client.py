"""HTTP client calling the standalone FastAPI AI Cognitive Triage Microservice."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class FastAPIAITriageClient:
    """
    Calls `{AI_SERVICE_URL}/api/v1/triage/analyze` with bounded timeout and retry.
    Returns `None` if the AI container is unreachable so Django falls back seamlessly
    to local deterministic triage pipelines.
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        max_retries: int = 2,
    ):
        self.base_url = (
            base_url or getattr(settings, "AI_SERVICE_URL", "http://ai-service:8001")
        ).rstrip("/")
        self.timeout_seconds = float(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "AI_SERVICE_TIMEOUT_SECONDS", 8.0)
        )
        self.max_retries = max_retries

    def analyze(
        self,
        *,
        text_bn: str = "",
        text_en: str = "",
        voice_audio_url: str = "",
        photo_urls: list[str] | None = None,
        lat: float | None = None,
        lon: float | None = None,
        hint_dialect: str = "",
        override_confidence: float | None = None,
    ) -> dict[str, Any] | None:
        payload = {
            "text_bn": text_bn,
            "text_en": text_en,
            "voice_audio_url": voice_audio_url,
            "photo_urls": photo_urls or [],
            "lat": lat,
            "lon": lon,
            "hint_dialect": hint_dialect,
            "override_confidence": override_confidence,
        }
        url = f"{self.base_url}/api/v1/triage/analyze"

        for attempt in range(1, self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.post(url, json=payload)
                    resp.raise_for_status()
                    return resp.json()
            except Exception as exc:
                logger.warning(
                    "FastAPI ai-service attempt %d/%d failed (%s): %s",
                    attempt,
                    self.max_retries,
                    url,
                    exc,
                )
                if attempt < self.max_retries:
                    time.sleep(0.25 * attempt)
        return None
