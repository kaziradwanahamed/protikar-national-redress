"""
Multimodal Pre-Processing Services:
  - Bangla / Banglish / Regional Dialect ASR (Whisper / Conformer HTTP worker hook + local mock)
  - Vision-Language Model (VLM) photo evidence validation + Bangla OCR receipt/reference extractor
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from django.conf import settings


BANGLA_DIGIT_MAP = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize_bangla_digits(text: str) -> str:
    """Convert Bangla numerals (০-৯) to ASCII digits (0-9) for reference ID extraction."""
    return (text or "").translate(BANGLA_DIGIT_MAP)


@dataclass(frozen=True)
class ASRResult:
    transcript_bn: str
    transcript_en: str
    detected_dialect: str
    confidence: float


@dataclass(frozen=True)
class VisionOCRResult:
    evidence_valid: bool
    evidence_labels: list[str] = field(default_factory=list)
    extracted_refs: dict[str, Any] = field(default_factory=dict)
    raw_ocr_text: str = ""


class BaseASRProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_url: str, hint_dialect: str = "") -> ASRResult:
        raise NotImplementedError


class BaseVisionOCRProvider(ABC):
    @abstractmethod
    def analyze_photos(self, photo_urls: list[str], context_text: str = "") -> VisionOCRResult:
        raise NotImplementedError


class WhisperConformerHTTPProvider(BaseASRProvider):
    """Production HTTP client calling FastAPI Whisper-large-v3 / Bangla-Conformer worker."""

    def __init__(self, timeout_seconds: float = 25.0):
        self.base_url = getattr(settings, "AI_WORKER_BASE_URL", "http://ai-worker:8001").rstrip("/")
        self.api_key = getattr(settings, "AI_WORKER_API_KEY", "")
        self.timeout_seconds = timeout_seconds

    def transcribe(self, audio_url: str, hint_dialect: str = "") -> ASRResult:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(
                f"{self.base_url}/v1/asr/transcribe",
                json={"audio_url": audio_url, "hint_dialect": hint_dialect},
                headers={"X-API-Key": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        return ASRResult(
            transcript_bn=data.get("transcript_bn", ""),
            transcript_en=data.get("transcript_en", ""),
            detected_dialect=data.get("detected_dialect", "standard_bn"),
            confidence=float(data.get("confidence", 0.9)),
        )


class MockBanglaASRProvider(BaseASRProvider):
    """Deterministic local dev/test ASR provider supporting Bangla, Banglish & regional dialects."""

    def transcribe(self, audio_url: str, hint_dialect: str = "") -> ASRResult:
        lower_url = (audio_url or "").lower()
        if "sylhet" in lower_url or hint_dialect == "sylheti":
            return ASRResult(
                transcript_bn="গুলশান রাস্তায় ওয়াসার পানির পাইপ ফেটে গেছে এবং রাস্তা ভেঙে গেছে।",
                transcript_en="WASA water pipe burst on Gulshan road and damaged the road surface.",
                detected_dialect="sylheti",
                confidence=0.91,
            )
        if "ctg" in lower_url or "chattogram" in lower_url:
            return ASRResult(
                transcript_bn="ডেসকোর বিদ্যুতের খুঁটি ভেঙে তার ঝুলে আছে, খুব বিপদজনক।",
                transcript_en="DESCO electric pole snapped with hanging live wire, very dangerous.",
                detected_dialect="chittagonian",
                confidence=0.93,
            )
        return ASRResult(
            transcript_bn="মিরপুর ১০ নম্বরে ওয়াসার পানির লাইন ফেটে রাস্তা তলিয়ে গেছে।",
            transcript_en="Dhaka WASA water line burst at Mirpur-10 flooding the road.",
            detected_dialect=hint_dialect or "standard_bn",
            confidence=0.92,
        )


class VLMOCRHTTPProvider(BaseVisionOCRProvider):
    """Production HTTP client calling FastAPI Vision-Language Model + Bangla OCR worker."""

    def __init__(self, timeout_seconds: float = 25.0):
        self.base_url = getattr(settings, "AI_WORKER_BASE_URL", "http://ai-worker:8001").rstrip("/")
        self.api_key = getattr(settings, "AI_WORKER_API_KEY", "")
        self.timeout_seconds = timeout_seconds

    def analyze_photos(self, photo_urls: list[str], context_text: str = "") -> VisionOCRResult:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(
                f"{self.base_url}/v1/vision/validate-and-ocr",
                json={"photo_urls": photo_urls, "context_text": context_text},
                headers={"X-API-Key": self.api_key},
            )
            resp.raise_for_status()
            data = resp.json()
        return VisionOCRResult(
            evidence_valid=bool(data.get("evidence_valid", True)),
            evidence_labels=list(data.get("evidence_labels", [])),
            extracted_refs=dict(data.get("extracted_refs", {})),
            raw_ocr_text=data.get("raw_ocr_text", ""),
        )


class MockVLMOCRProvider(BaseVisionOCRProvider):
    """Deterministic local dev/test VLM + Bangla OCR extractor."""

    REF_PATTERNS = {
        "egp_tender_id": re.compile(r"EGP[- ]?(\d{4}[- ]?\d{4,8})", re.IGNORECASE),
        "d_nothi_ref": re.compile(r"(\d{2}\.\d{2}\.\d{4}\.\d{3}\.\d{2}\.\d{3}\.\d{2}\.\d+)"),
        "desco_account": re.compile(r"DESCO[- ]?([A-Z0-9]{5,12})", re.IGNORECASE),
        "dwasa_account": re.compile(r"DWASA[- ]?([A-Z0-9]{5,12})", re.IGNORECASE),
        "receipt_no": re.compile(r"(?:receipt|রসিদ|চালান)[:#\- ]*([A-Z0-9\-]{4,20})", re.IGNORECASE),
    }

    def analyze_photos(self, photo_urls: list[str], context_text: str = "") -> VisionOCRResult:
        combined = normalize_bangla_digits(" ".join(photo_urls) + " " + (context_text or ""))
        labels: list[str] = []
        lower = combined.lower()
        if any(k in lower for k in ("pipe", "water", "wasa", "পানি", "পাইপ")):
            labels.append("burst_water_pipe")
        if any(k in lower for k in ("pole", "wire", "desco", "dpdc", "খুঁটি", "বিদ্যুৎ")):
            labels.append("snapped_electric_pole")
        if any(k in lower for k in ("road", "pothole", "রাস্তা", "গর্ত", "bridge")):
            labels.append("damaged_road_surface")
        if not labels:
            labels.append("civic_evidence_photo")

        extracted: dict[str, str] = {}
        for key, pattern in self.REF_PATTERNS.items():
            m = pattern.search(combined)
            if m:
                extracted[key] = m.group(1)

        evidence_valid = "invalid_meme" not in lower and "spam_image" not in lower
        return VisionOCRResult(
            evidence_valid=evidence_valid,
            evidence_labels=labels,
            extracted_refs=extracted,
            raw_ocr_text=combined[:500],
        )


class MultimodalPreprocessor:
    """Facade selecting mock or production FastAPI ASR & VLM/OCR providers."""

    def __init__(self):
        mode = getattr(settings, "AI_PROVIDER_MODE", "mock").lower()
        if mode == "production":
            self.asr: BaseASRProvider = WhisperConformerHTTPProvider()
            self.vlm_ocr: BaseVisionOCRProvider = VLMOCRHTTPProvider()
        else:
            self.asr = MockBanglaASRProvider()
            self.vlm_ocr = MockVLMOCRProvider()

    def run(
        self,
        *,
        raw_text_bn: str = "",
        raw_text_en: str = "",
        voice_audio_url: str = "",
        photo_urls: list[str] | None = None,
    ) -> tuple[str, str, ASRResult | None, VisionOCRResult | None]:
        asr_res = self.asr.transcribe(voice_audio_url) if voice_audio_url else None
        merged_bn = " ".join(filter(None, [raw_text_bn, asr_res.transcript_bn if asr_res else ""])).strip()
        merged_en = " ".join(filter(None, [raw_text_en, asr_res.transcript_en if asr_res else ""])).strip()
        vlm_res = (
            self.vlm_ocr.analyze_photos(photo_urls, context_text=f"{merged_bn} {merged_en}")
            if photo_urls
            else None
        )
        return merged_bn, merged_en, asr_res, vlm_res
