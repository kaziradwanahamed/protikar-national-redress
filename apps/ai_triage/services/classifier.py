"""
Hierarchical Multi-Label Classifier across 58+ Bangladesh Ministries/Divisions
and 350+ Directorates/Agencies with Confidence-Gated Routing:
  - >= 85%: Auto-route immediately.
  - 60%–84%: Route to primary prediction with 1-click "Reassign Department" flag for GRO.
  - < 60%: Return 1–2 clarifying questions to citizen before finalizing ticket creation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
from django.conf import settings

from apps.ai_triage.models import TriageRun
from apps.complaints.models import Complaint
from apps.organogram.models import ServiceAreaPolygon


# Core active routing taxonomy entries backed by full 58-Ministry / 350+-Agency registry metadata
AGENCY_ROUTING_RULES: list[dict[str, Any]] = [
    {
        "ministry_code": "MIN-LGRD",
        "ministry_name": "Local Government Division (MoLGRD&C)",
        "agency_code": "DWASA",
        "agency_name": "Dhaka WASA",
        "category_code": "WATER.BURST_PIPE_SUPPLY",
        "zone_type": ServiceAreaPolygon.ZoneType.WASA_MODS_ZONE,
        "engineering_phase": 2,  # Underground utility repair (after power safety, before road paving)
        "default_urgency": Complaint.UrgencyTier.P2,
        "keywords": ("wasa", "ওয়াসা", "water", "পানি", "pipe", "পাইপ", "sewer", "স্যুয়ারেজ", "burst", "ফেটে"),
    },
    {
        "ministry_code": "MIN-POWER",
        "ministry_name": "Power Division (MoPEMR)",
        "agency_code": "DESCO",
        "agency_name": "Dhaka Electric Supply Company (DESCO)",
        "category_code": "POWER.SNAPPED_POLE_OUTAGE",
        "zone_type": ServiceAreaPolygon.ZoneType.DESCO_FEEDER,
        "engineering_phase": 1,  # Power safety ALWAYS first
        "default_urgency": Complaint.UrgencyTier.P1,
        "keywords": ("desco", "ডেসকো", "pole", "খুঁটি", "electric", "বিদ্যুৎ", "wire", "তার", "transformer", "ট্রান্সফরমার", "snapped", "sparking"),
    },
    {
        "ministry_code": "MIN-POWER",
        "ministry_name": "Power Division (MoPEMR)",
        "agency_code": "DPDC",
        "agency_name": "Dhaka Power Distribution Company (DPDC)",
        "category_code": "POWER.FEEDER_FAULT",
        "zone_type": ServiceAreaPolygon.ZoneType.DPDC_FEEDER,
        "engineering_phase": 1,
        "default_urgency": Complaint.UrgencyTier.P1,
        "keywords": ("dpdc", "ডিপিডিসি", "motijheel power", "feeder", "ফিডার", "substation"),
    },
    {
        "ministry_code": "MIN-LGRD",
        "ministry_name": "Local Government Division (MoLGRD&C)",
        "agency_code": "CITY_CORP",
        "agency_name": "City Corporation (DNCC / DSCC)",
        "category_code": "URBAN_INFRA.ROAD_DRAINAGE_LIGHT",
        "zone_type": ServiceAreaPolygon.ZoneType.CITY_CORP_WARD,
        "engineering_phase": 3,  # Surface road repair AFTER power & WASA
        "default_urgency": Complaint.UrgencyTier.P3,
        "keywords": ("road", "রাস্তা", "pothole", "গর্ত", "drain", "ড্রেন", "waterlogging", "জলাবদ্ধতা", "streetlight", "লাইট", "dncc", "dscc", "garbage", "ময়লা"),
    },
    {
        "ministry_code": "MIN-RTHD",
        "ministry_name": "Road Transport and Highways Division",
        "agency_code": "RHD",
        "agency_name": "Roads and Highways Department (RHD)",
        "category_code": "HIGHWAY.DAMAGED_CORRIDOR",
        "zone_type": ServiceAreaPolygon.ZoneType.RHD_ROAD,
        "engineering_phase": 3,
        "default_urgency": Complaint.UrgencyTier.P2,
        "keywords": ("rhd", "সওজ", "highway", "মহাসড়ক", "n1", "jatrabari", "kanchpur", "flyover"),
    },
    {
        "ministry_code": "MIN-LGRD",
        "ministry_name": "Local Government Division (MoLGRD&C)",
        "agency_code": "LGED",
        "agency_name": "Local Government Engineering Department (LGED)",
        "category_code": "RURAL_ROAD.UPAZILA_CORRIDOR",
        "zone_type": ServiceAreaPolygon.ZoneType.LGED_ROAD,
        "engineering_phase": 3,
        "default_urgency": Complaint.UrgencyTier.P3,
        "keywords": ("lged", "এলজিইডি", "upazila road", "উপজেলা সড়ক", "savar", "সাভার", "ashulia", "আশুলিয়া", "culvert", "কালভার্ট"),
    },
    {
        "ministry_code": "MIN-HEALTH",
        "ministry_name": "Health Services Division (MoHFW)",
        "agency_code": "DGHS",
        "agency_name": "Directorate General of Health Services (DGHS)",
        "category_code": "HEALTH.HOSPITAL_SERVICE",
        "zone_type": ServiceAreaPolygon.ZoneType.BBS_DISTRICT,
        "engineering_phase": 2,
        "default_urgency": Complaint.UrgencyTier.P2,
        "keywords": ("hospital", "হাসপাতাল", "doctor", "ডাক্তার", "clinic", "ক্লিনিক", "medicine", "ওষুধ", "dghs"),
    },
    {
        "ministry_code": "MIN-LAND",
        "ministry_name": "Ministry of Land",
        "agency_code": "AC_LAND",
        "agency_name": "Assistant Commissioner (Land) / Mutation",
        "category_code": "LAND.MUTATION_KHATIAN",
        "zone_type": ServiceAreaPolygon.ZoneType.BBS_UPAZILA,
        "engineering_phase": 2,
        "default_urgency": Complaint.UrgencyTier.P3,
        "keywords": ("land", "ভূমি", "mutation", "নামজারি", "khatian", "খতিয়ান", "ac land", "পর্চা"),
    },
]

TAXONOMY_METADATA = {
    "total_ministries_divisions": 58,
    "total_directorates_agencies": 356,
}


@dataclass(frozen=True)
class LabelPrediction:
    ministry_code: str
    agency_code: str
    agency_name: str
    category_code: str
    zone_type: str
    engineering_phase: int
    urgency_tier: str
    confidence: float


@dataclass(frozen=True)
class ClassificationOutput:
    predictions: list[LabelPrediction]
    top_confidence: float
    routing_decision: str
    gro_one_click_reassign_flag: bool
    clarifying_questions: list[dict[str, str]] = field(default_factory=list)


class HierarchicalMultiLabelClassifier:
    """Multi-label classifier with 85% auto-route, 60-84% GRO reassign flag, and <60% clarification."""

    def __init__(self):
        self.auto_threshold = float(getattr(settings, "AI_AUTO_ROUTE_THRESHOLD", 0.85))
        self.gro_flag_threshold = float(getattr(settings, "AI_GRO_FLAG_THRESHOLD", 0.60))

    def classify(
        self,
        *,
        text_bn: str = "",
        text_en: str = "",
        vlm_labels: list[str] | None = None,
        override_confidence: float | None = None,
    ) -> ClassificationOutput:
        if getattr(settings, "AI_PROVIDER_MODE", "mock").lower() == "production":
            return self._classify_remote(text_bn=text_bn, text_en=text_en, vlm_labels=vlm_labels or [])

        combined = f"{text_bn} {text_en} {' '.join(vlm_labels or [])}".lower()
        matched: list[LabelPrediction] = []

        for rule in AGENCY_ROUTING_RULES:
            hits = sum(1 for kw in rule["keywords"] if kw in combined)
            if hits > 0:
                # 1 keyword hit -> ~0.72 (GRO reassign band), >=2 hits -> 0.88–0.96 (auto-route band)
                score = min(0.97, 0.58 + (hits * 0.15))
                if override_confidence is not None:
                    score = override_confidence
                matched.append(
                    LabelPrediction(
                        ministry_code=rule["ministry_code"],
                        agency_code=rule["agency_code"],
                        agency_name=rule["agency_name"],
                        category_code=rule["category_code"],
                        zone_type=rule["zone_type"],
                        engineering_phase=rule["engineering_phase"],
                        urgency_tier=rule["default_urgency"],
                        confidence=round(score, 3),
                    )
                )

        matched.sort(key=lambda p: p.confidence, reverse=True)

        if not matched:
            top_conf = override_confidence if override_confidence is not None else 0.42
        else:
            top_conf = matched[0].confidence

        return self._apply_confidence_gate(matched, top_conf)

    def _apply_confidence_gate(
        self, predictions: list[LabelPrediction], top_confidence: float
    ) -> ClassificationOutput:
        if top_confidence >= self.auto_threshold and predictions:
            return ClassificationOutput(
                predictions=predictions,
                top_confidence=top_confidence,
                routing_decision=TriageRun.RoutingDecision.AUTO_ROUTED,
                gro_one_click_reassign_flag=False,
                clarifying_questions=[],
            )
        if top_confidence >= self.gro_flag_threshold and predictions:
            return ClassificationOutput(
                predictions=predictions,
                top_confidence=top_confidence,
                routing_decision=TriageRun.RoutingDecision.GRO_REASSIGN_FLAGGED,
                gro_one_click_reassign_flag=True,
                clarifying_questions=[],
            )
        return ClassificationOutput(
            predictions=predictions,
            top_confidence=top_confidence,
            routing_decision=TriageRun.RoutingDecision.CLARIFICATION_REQUIRED,
            gro_one_click_reassign_flag=False,
            clarifying_questions=[
                {
                    "en": "Which public service or utility is affected (e.g., water supply, electricity, road, healthcare, or land)?",
                    "bn": "কোন সরকারি সেবা বা ইউটিলিটি ক্ষতিগ্রস্ত হয়েছে (যেমন: পানি, বিদ্যুৎ, রাস্তা, স্বাস্থ্য, বা ভূমি)?",
                },
                {
                    "en": "Please confirm the exact ward, road/landmark, or upazila where this issue is located.",
                    "bn": "অনুগ্রহ করে সমস্যাটির সঠিক ওয়ার্ড, রাস্তা/পরিচিত স্থান বা উপজেলা নিশ্চিত করুন।",
                },
            ],
        )

    def _classify_remote(
        self, *, text_bn: str, text_en: str, vlm_labels: list[str]
    ) -> ClassificationOutput:
        base_url = getattr(settings, "AI_WORKER_BASE_URL", "http://ai-worker:8001").rstrip("/")
        api_key = getattr(settings, "AI_WORKER_API_KEY", "")
        with httpx.Client(timeout=20.0) as client:
            resp = client.post(
                f"{base_url}/v1/classify/hierarchical",
                json={"text_bn": text_bn, "text_en": text_en, "vlm_labels": vlm_labels},
                headers={"X-API-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()

        preds = [
            LabelPrediction(
                ministry_code=p["ministry_code"],
                agency_code=p["agency_code"],
                agency_name=p.get("agency_name", p["agency_code"]),
                category_code=p["category_code"],
                zone_type=p.get("zone_type", ServiceAreaPolygon.ZoneType.CITY_CORP_WARD),
                engineering_phase=int(p.get("engineering_phase", 2)),
                urgency_tier=p.get("urgency_tier", Complaint.UrgencyTier.P3),
                confidence=float(p["confidence"]),
            )
            for p in data.get("predictions", [])
        ]
        top_conf = preds[0].confidence if preds else 0.0
        return self._apply_confidence_gate(preds, top_conf)
