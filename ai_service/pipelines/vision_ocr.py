"""
Vision-Language Model (VLM) & Bangla OCR Pipeline.
Validates photo evidence, scores hazard severity, normalizes Bangla digits (০-৯),
and extracts receipt numbers, e-GP IDs, D-Nothi refs, and utility consumer numbers.
"""

from __future__ import annotations

import os
import re
import httpx


BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize_bangla_digits(text: str) -> str:
    return (text or "").translate(BANGLA_DIGITS)


class VisionOCRPipeline:
    """Pluggable VLM + Bangla OCR analyzer controlled via VISION_BACKEND=mock|http_api."""

    REF_PATTERNS = {
        "egp_tender_id": re.compile(r"EGP[- ]?(\d{4}[- ]?\d{4,8})", re.IGNORECASE),
        "d_nothi_ref": re.compile(r"(\d{2}\.\d{2}\.\d{4}\.\d{3}\.\d{2}\.\d{3}\.\d{2}\.\d+)"),
        "desco_account": re.compile(r"DESCO[- ]?([A-Z0-9]{4,12})", re.IGNORECASE),
        "dpdc_account": re.compile(r"DPDC[- ]?([A-Z0-9]{4,12})", re.IGNORECASE),
        "dwasa_account": re.compile(r"DWASA[- ]?([A-Z0-9]{4,12})", re.IGNORECASE),
        "mutation_receipt": re.compile(r"(?:mutation|নামজারি|রসিদ|receipt)[:#\- ]*([A-Z0-9\-]{4,20})", re.IGNORECASE),
    }

    def __init__(self):
        self.backend = os.getenv("VISION_BACKEND", "mock").lower()
        self.external_vlm_url = os.getenv("EXTERNAL_VLM_URL", "")

    def analyze(self, photo_urls: list[str], context_text: str = "") -> dict:
        if self.backend == "http_api" and self.external_vlm_url:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(
                    self.external_vlm_url,
                    json={"photo_urls": photo_urls, "context_text": context_text},
                )
                resp.raise_for_status()
                return resp.json()

        combined = normalize_bangla_digits(" ".join(photo_urls) + " " + (context_text or ""))
        lower = combined.lower()

        labels: list[str] = []
        severity = "LOW"

        if any(k in lower for k in ("transformer", "spark", "live wire", "pole", "বিদ্যুৎ", "খুঁটি", "তার")):
            labels.append("electrical_hazard_pole_transformer")
            severity = "CRITICAL"
        if any(k in lower for k in ("flood", "embankment", "trapped", "বন্যা", "বাঁধ", "ডুবে")):
            labels.append("flood_inundation")
            severity = "CRITICAL" if severity != "CRITICAL" else severity
        if any(k in lower for k in ("pipe", "water", "wasa", "পানি", "পাইপ")):
            labels.append("burst_water_pipe")
            if severity == "LOW":
                severity = "HIGH"
        if any(k in lower for k in ("road", "pothole", "garbage", "রাস্তা", "গর্ত", "ময়লা")):
            labels.append("urban_road_or_waste_damage")
            if severity == "LOW":
                severity = "MEDIUM"
        if any(k in lower for k in ("receipt", "mutation", "khatian", "রসিদ", "নামজারি")):
            labels.append("official_document_receipt")

        if not labels:
            labels.append("civic_evidence_photo")

        extracted_refs: dict[str, str] = {}
        for key, pattern in self.REF_PATTERNS.items():
            match = pattern.search(combined)
            if match:
                extracted_refs[key] = match.group(1)

        evidence_valid = not any(bad in lower for bad in ("spam_image", "invalid_meme", "blank_photo"))
        return {
            "evidence_valid": evidence_valid,
            "hazard_severity": severity,
            "evidence_labels": labels,
            "extracted_refs": extracted_refs,
            "raw_ocr_text": combined[:500],
        }
