"""Standalone FastAPI AI Cognitive Triage Microservice for the Government of Bangladesh."""

from __future__ import annotations

from fastapi import FastAPI

from ai_service.pipelines.asr import BanglaDialectASRPipeline
from ai_service.pipelines.classifier import HierarchicalDepartmentClassifier
from ai_service.pipelines.compound_splitter import CompoundSplitterPipeline
from ai_service.pipelines.geo_ner import BanglaGeoNERPipeline
from ai_service.pipelines.vision_ocr import VisionOCRPipeline
from ai_service.schemas import (
    ASRRequest,
    ASRResponse,
    TriageAnalyzeRequest,
    TriageAnalyzeResponse,
    VisionOCRRequest,
    VisionOCRResponse,
)

app = FastAPI(
    title="Bangladesh National Grievance — AI Cognitive Triage Service",
    description="Multimodal Bangla/Dialect ASR, VLM+OCR, 58-Ministry/350+-Agency Classifier, Geo-NER & Compound Splitter.",
    version="1.0.0",
)

asr_pipeline = BanglaDialectASRPipeline()
vision_pipeline = VisionOCRPipeline()
classifier_pipeline = HierarchicalDepartmentClassifier()
splitter_pipeline = CompoundSplitterPipeline()
geo_ner_pipeline = BanglaGeoNERPipeline()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "bd-grievance-ai-service",
        "asr_backend": asr_pipeline.backend,
        "vision_backend": vision_pipeline.backend,
    }


@app.post("/api/v1/triage/transcribe", response_model=ASRResponse)
def transcribe_voice(req: ASRRequest):
    return ASRResponse(**asr_pipeline.transcribe(req.audio_url, hint_dialect=req.hint_dialect))


@app.post("/api/v1/triage/ocr", response_model=VisionOCRResponse)
def analyze_vision_ocr(req: VisionOCRRequest):
    return VisionOCRResponse(
        **vision_pipeline.analyze(req.photo_urls, context_text=req.context_text)
    )


@app.post("/api/v1/triage/analyze", response_model=TriageAnalyzeResponse)
def analyze_complaint(req: TriageAnalyzeRequest):
    asr_out = (
        asr_pipeline.transcribe(req.voice_audio_url, hint_dialect=req.hint_dialect)
        if req.voice_audio_url
        else None
    )
    merged_bn = " ".join(filter(None, [req.text_bn, asr_out["transcript_bn"] if asr_out else ""])).strip()
    merged_en = " ".join(filter(None, [req.text_en, asr_out["transcript_en"] if asr_out else ""])).strip()

    vlm_out = (
        vision_pipeline.analyze(req.photo_urls, context_text=f"{merged_bn} {merged_en}")
        if req.photo_urls
        else None
    )

    clf = classifier_pipeline.classify(
        text_bn=merged_bn,
        text_en=merged_en,
        vlm_labels=vlm_out["evidence_labels"] if vlm_out else [],
        override_confidence=req.override_confidence,
    )
    geo = geo_ner_pipeline.analyze(text_bn=merged_bn, text_en=merged_en)
    is_compound, child_subtickets = splitter_pipeline.build_plan(
        predictions=clf["predictions"],
        narrative_en=merged_en,
        narrative_bn=merged_bn,
    )

    primary = clf["predictions"][0] if clf["predictions"] else None
    is_p1 = bool(geo["is_life_safety_p1"] or (primary and primary["urgency_tier"] == "P1"))
    recommended_tier = "P1" if is_p1 else (primary["urgency_tier"] if primary else "P3")

    return TriageAnalyzeResponse(
        asr=ASRResponse(**asr_out) if asr_out else None,
        vision_ocr=VisionOCRResponse(**vlm_out) if vlm_out else None,
        predictions=clf["predictions"],
        primary_ministry_code=primary["ministry_code"] if primary else "",
        primary_agency_code=primary["agency_code"] if primary else "",
        primary_category_code=primary["category_code"] if primary else "",
        confidence=clf["confidence"],
        auto_route=clf["auto_route"],
        needs_gro_review=clf["needs_gro_review"],
        clarifying_questions=clf["clarifying_questions"],
        is_compound=is_compound,
        child_subtickets=child_subtickets,
        geo_ner=geo,
        is_life_safety_p1=is_p1,
        recommended_urgency_tier=recommended_tier,
        taxonomy_coverage=clf["taxonomy_coverage"],
    )
