"""Typed Pydantic v2 request/response contracts for the FastAPI AI Cognitive Triage Service."""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ASRRequest(BaseModel):
    audio_url: str = Field(..., min_length=3, max_length=2048)
    hint_dialect: str = Field(default="", max_length=32)


class ASRResponse(BaseModel):
    transcript_bn: str
    transcript_en: str
    detected_dialect: str
    backend_used: str
    confidence: float = Field(ge=0.0, le=1.0)


class VisionOCRRequest(BaseModel):
    photo_urls: list[str] = Field(default_factory=list)
    context_text: str = Field(default="", max_length=4000)


class VisionOCRResponse(BaseModel):
    evidence_valid: bool
    hazard_severity: str
    evidence_labels: list[str] = Field(default_factory=list)
    extracted_refs: dict[str, str] = Field(default_factory=dict)
    raw_ocr_text: str = ""


class DepartmentPrediction(BaseModel):
    ministry_code: str
    ministry_name: str
    agency_code: str
    agency_name: str
    category_code: str
    zone_type: str
    urgency_tier: str
    confidence: float = Field(ge=0.0, le=1.0)
    step_order: int = 1


class ChildSubTicketPlan(BaseModel):
    step_order: int
    agency_code: str
    ministry_code: str
    category_code: str
    zone_type: str
    urgency_tier: str
    summary_en: str
    depends_on_step: int | None = None
    dependency_reason: str = ""


class GeoNERResult(BaseModel):
    division: str = ""
    district: str = ""
    upazila: str = ""
    union_or_ward: str = ""
    bbs_geo_code: str = ""
    road_ownership_hint: str = ""
    extracted_entities: list[str] = Field(default_factory=list)
    is_life_safety_p1: bool = False
    matched_rescue_keywords: list[str] = Field(default_factory=list)


class ClarifyingQuestion(BaseModel):
    en: str
    bn: str


class TriageAnalyzeRequest(BaseModel):
    text_bn: str = ""
    text_en: str = ""
    voice_audio_url: str = ""
    photo_urls: list[str] = Field(default_factory=list)
    lat: float | None = Field(default=None, ge=-90.0, le=90.0)
    lon: float | None = Field(default=None, ge=-180.0, le=180.0)
    hint_dialect: str = ""
    override_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class TriageAnalyzeResponse(BaseModel):
    asr: ASRResponse | None = None
    vision_ocr: VisionOCRResponse | None = None
    predictions: list[DepartmentPrediction] = Field(default_factory=list)
    primary_ministry_code: str = ""
    primary_agency_code: str = ""
    primary_category_code: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    auto_route: bool = False
    needs_gro_review: bool = False
    clarifying_questions: list[ClarifyingQuestion] = Field(default_factory=list)
    is_compound: bool = False
    child_subtickets: list[ChildSubTicketPlan] = Field(default_factory=list)
    geo_ner: GeoNERResult = Field(default_factory=GeoNERResult)
    is_life_safety_p1: bool = False
    recommended_urgency_tier: str = "P3"
    taxonomy_coverage: dict[str, Any] = Field(default_factory=dict)
