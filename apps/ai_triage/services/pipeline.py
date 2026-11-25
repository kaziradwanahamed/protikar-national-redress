"""
End-to-End AI Triage Orchestrator:
  1. Calls standalone FastAPI AI Microservice (`AI_SERVICE_URL/api/v1/triage/analyze`).
  2. Automatically falls back to local deterministic pipelines if ai-service is unreachable.
  3. Persists TriageRun, routes >=85% immediately, flags 60-84% for 1-click GRO reassign,
     halts <60% with interactive clarifying questions, splits compound narratives into
     Parent + sequenced Child Sub-Tickets, and triggers P1 Life-Safety Fast-Lane.
"""

from __future__ import annotations

from django.db import transaction

from apps.ai_triage.models import TriageRun
from apps.ai_triage.services.ai_client import FastAPIAITriageClient
from apps.ai_triage.services.classifier import (
    HierarchicalMultiLabelClassifier,
    LabelPrediction,
)
from apps.ai_triage.services.deduplicator import SpatialDeduplicationService
from apps.ai_triage.services.geo_resolver import PostGISJurisdictionResolver
from apps.ai_triage.services.multimodal import MultimodalPreprocessor
from apps.ai_triage.services.splitter import CompoundComplaintSplitter
from apps.complaints.models import AuditLog, Complaint
from apps.disaster.services.h3_surge_pipeline import H3SurgeIngestionService
from apps.workflow.services.sla_service import TieredSLAService


class AITriageOrchestrator:
    """Orchestrates FastAPI AI Triage (with local fallback), PostGIS resolution, dedup & splitting."""

    @classmethod
    @transaction.atomic
    def process_complaint(
        cls,
        *,
        complaint: Complaint,
        photo_urls: list[str] | None = None,
        override_confidence: float | None = None,
        use_remote_ai: bool = True,
    ) -> TriageRun:
        remote_data = None
        if use_remote_ai:
            remote_data = FastAPIAITriageClient().analyze(
                text_bn=complaint.raw_text_bn,
                text_en=complaint.raw_text_en,
                voice_audio_url=complaint.voice_audio_url,
                photo_urls=photo_urls or [],
                lat=complaint.geo_point.y if complaint.geo_point else None,
                lon=complaint.geo_point.x if complaint.geo_point else None,
                override_confidence=override_confidence,
            )

        if remote_data is not None:
            return cls._apply_remote_analysis(complaint=complaint, data=remote_data)

        return cls._run_local_fallback(
            complaint=complaint,
            photo_urls=photo_urls,
            override_confidence=override_confidence,
        )

    @classmethod
    def _apply_remote_analysis(cls, *, complaint: Complaint, data: dict) -> TriageRun:
        asr = data.get("asr") or {}
        vlm = data.get("vision_ocr") or {}
        geo_ner = data.get("geo_ner") or {}
        raw_preds = data.get("predictions") or []

        if asr.get("transcript_bn") and asr["transcript_bn"] not in complaint.raw_text_bn:
            complaint.raw_text_bn = f"{complaint.raw_text_bn} {asr['transcript_bn']}".strip()
        if asr.get("transcript_en") and asr["transcript_en"] not in complaint.raw_text_en:
            complaint.raw_text_en = f"{complaint.raw_text_en} {asr['transcript_en']}".strip()

        jurisdiction = PostGISJurisdictionResolver.resolve(
            geo_point=complaint.geo_point,
            text_bn=complaint.raw_text_bn,
            text_en=complaint.raw_text_en,
        )
        if complaint.geo_point is None and jurisdiction.resolved_point is not None:
            complaint.geo_point = jurisdiction.resolved_point
        if not complaint.admin_geo_code:
            complaint.admin_geo_code = jurisdiction.bbs_geo_code or geo_ner.get("bbs_geo_code", "")

        confidence = float(data.get("confidence", 0.0))
        complaint.ai_category_code = data.get("primary_category_code", "")
        complaint.ai_confidence = confidence
        complaint.urgency_tier = data.get("recommended_urgency_tier", complaint.urgency_tier)
        complaint.save(
            update_fields=[
                "raw_text_bn",
                "raw_text_en",
                "geo_point",
                "admin_geo_code",
                "ai_category_code",
                "ai_confidence",
                "urgency_tier",
                "updated_at",
            ]
        )

        # Trigger P1 Life-Safety Fast-Lane if flagged by Bangla Geo-NER
        if data.get("is_life_safety_p1") and complaint.geo_point is not None:
            H3SurgeIngestionService.ingest_surge_report(
                lat=complaint.geo_point.y,
                lon=complaint.geo_point.x,
                message=complaint.raw_text_en or complaint.raw_text_bn,
                complaint=complaint,
            )

        clarifying = data.get("clarifying_questions") or []
        needs_gro_review = bool(data.get("needs_gro_review", False))
        auto_route = bool(data.get("auto_route", False))

        if clarifying and not auto_route and not needs_gro_review:
            final_decision = TriageRun.RoutingDecision.CLARIFICATION_REQUIRED
        else:
            dedup = SpatialDeduplicationService.deduplicate_and_cluster(complaint=complaint)
            if dedup.is_duplicate:
                final_decision = TriageRun.RoutingDecision.MERGED_DUPLICATE
            elif data.get("is_compound") and len(raw_preds) >= 2:
                label_objs = [
                    LabelPrediction(
                        ministry_code=p["ministry_code"],
                        agency_code=p["agency_code"],
                        agency_name=p.get("agency_name", p["agency_code"]),
                        category_code=p["category_code"],
                        zone_type=p.get("zone_type", "CITY_CORP_WARD"),
                        engineering_phase=int(p.get("step_order", 2)),
                        urgency_tier=p.get("urgency_tier", "P3"),
                        confidence=float(p.get("confidence", confidence)),
                    )
                    for p in raw_preds
                ]
                CompoundComplaintSplitter.split(
                    parent_complaint=complaint,
                    predictions=label_objs,
                    jurisdiction=jurisdiction,
                )
                final_decision = TriageRun.RoutingDecision.COMPOUND_SPLIT
            else:
                final_decision = (
                    TriageRun.RoutingDecision.AUTO_ROUTED
                    if auto_route
                    else TriageRun.RoutingDecision.GRO_REASSIGN_FLAGGED
                )
                primary_zone_type = raw_preds[0].get("zone_type", "") if raw_preds else ""
                target_seat = PostGISJurisdictionResolver.pick_seat_for_zone_type(
                    jurisdiction, primary_zone_type
                )
                if target_seat:
                    TieredSLAService.route_complaint(
                        complaint=complaint,
                        target_seat_id=target_seat,
                        actor_id="SYSTEM-FASTAPI-AI",
                    )

        triage_run = TriageRun.objects.create(
            complaint=complaint,
            asr_transcript_bn=asr.get("transcript_bn", ""),
            asr_transcript_en=asr.get("transcript_en", ""),
            detected_dialect=asr.get("detected_dialect", ""),
            vlm_evidence_valid=bool(vlm.get("evidence_valid", True)),
            vlm_evidence_labels=vlm.get("evidence_labels", []),
            ocr_extracted_refs=vlm.get("extracted_refs", {}),
            primary_ministry_code=data.get("primary_ministry_code", ""),
            primary_agency_code=data.get("primary_agency_code", ""),
            predicted_labels=raw_preds,
            confidence_score=confidence,
            routing_decision=final_decision,
            gro_one_click_reassign_flag=needs_gro_review,
            clarifying_questions=clarifying,
            extracted_geo_entities=geo_ner.get("extracted_entities", []),
            resolved_zone_codes=[z.zone_code for z in jurisdiction.matched_zones],
        )

        AuditLog.objects.create(
            complaint=complaint,
            actor_id="SYSTEM-FASTAPI-AI",
            actor_role="SYSTEM",
            action=f"AI_TRIAGE_{final_decision}",
            entity_type="TriageRun",
            entity_id=str(triage_run.run_id),
            payload={
                "source": "fastapi_ai_service",
                "confidence_score": confidence,
                "is_life_safety_p1": bool(data.get("is_life_safety_p1", False)),
                "primary_agency_code": triage_run.primary_agency_code,
            },
        )
        return triage_run

    @classmethod
    def _run_local_fallback(
        cls,
        *,
        complaint: Complaint,
        photo_urls: list[str] | None = None,
        override_confidence: float | None = None,
    ) -> TriageRun:
        preprocessor = MultimodalPreprocessor()
        merged_bn, merged_en, asr_res, vlm_res = preprocessor.run(
            raw_text_bn=complaint.raw_text_bn,
            raw_text_en=complaint.raw_text_en,
            voice_audio_url=complaint.voice_audio_url,
            photo_urls=photo_urls,
        )
        if merged_bn and merged_bn != complaint.raw_text_bn:
            complaint.raw_text_bn = merged_bn
        if merged_en and merged_en != complaint.raw_text_en:
            complaint.raw_text_en = merged_en

        classifier = HierarchicalMultiLabelClassifier()
        clf_out = classifier.classify(
            text_bn=merged_bn,
            text_en=merged_en,
            vlm_labels=vlm_res.evidence_labels if vlm_res else [],
            override_confidence=override_confidence,
        )

        jurisdiction = PostGISJurisdictionResolver.resolve(
            geo_point=complaint.geo_point,
            text_bn=merged_bn,
            text_en=merged_en,
        )
        if complaint.geo_point is None and jurisdiction.resolved_point is not None:
            complaint.geo_point = jurisdiction.resolved_point
        if not complaint.admin_geo_code and jurisdiction.bbs_geo_code:
            complaint.admin_geo_code = jurisdiction.bbs_geo_code

        primary_pred = clf_out.predictions[0] if clf_out.predictions else None
        if primary_pred:
            complaint.ai_category_code = primary_pred.category_code
            complaint.ai_confidence = clf_out.top_confidence
            complaint.urgency_tier = primary_pred.urgency_tier

        complaint.save(
            update_fields=[
                "raw_text_bn",
                "raw_text_en",
                "geo_point",
                "admin_geo_code",
                "ai_category_code",
                "ai_confidence",
                "urgency_tier",
                "updated_at",
            ]
        )

        final_decision = clf_out.routing_decision
        if clf_out.routing_decision != TriageRun.RoutingDecision.CLARIFICATION_REQUIRED and primary_pred:
            dedup = SpatialDeduplicationService.deduplicate_and_cluster(complaint=complaint)
            if dedup.is_duplicate:
                final_decision = TriageRun.RoutingDecision.MERGED_DUPLICATE
            elif len({p.agency_code for p in clf_out.predictions}) >= 2:
                CompoundComplaintSplitter.split(
                    parent_complaint=complaint,
                    predictions=clf_out.predictions,
                    jurisdiction=jurisdiction,
                )
                final_decision = TriageRun.RoutingDecision.COMPOUND_SPLIT
            else:
                target_seat = PostGISJurisdictionResolver.pick_seat_for_zone_type(
                    jurisdiction, primary_pred.zone_type
                )
                if target_seat:
                    TieredSLAService.route_complaint(
                        complaint=complaint,
                        target_seat_id=target_seat,
                        actor_id="SYSTEM-AI-TRIAGE",
                    )

        triage_run = TriageRun.objects.create(
            complaint=complaint,
            asr_transcript_bn=asr_res.transcript_bn if asr_res else "",
            asr_transcript_en=asr_res.transcript_en if asr_res else "",
            detected_dialect=asr_res.detected_dialect if asr_res else "",
            vlm_evidence_valid=vlm_res.evidence_valid if vlm_res else True,
            vlm_evidence_labels=vlm_res.evidence_labels if vlm_res else [],
            ocr_extracted_refs=vlm_res.extracted_refs if vlm_res else {},
            primary_ministry_code=primary_pred.ministry_code if primary_pred else "",
            primary_agency_code=primary_pred.agency_code if primary_pred else "",
            predicted_labels=[
                {
                    "ministry_code": p.ministry_code,
                    "agency_code": p.agency_code,
                    "category_code": p.category_code,
                    "confidence": p.confidence,
                    "engineering_phase": p.engineering_phase,
                }
                for p in clf_out.predictions
            ],
            confidence_score=clf_out.top_confidence,
            routing_decision=final_decision,
            gro_one_click_reassign_flag=clf_out.gro_one_click_reassign_flag,
            clarifying_questions=clf_out.clarifying_questions,
            extracted_geo_entities=jurisdiction.extracted_geo_entities,
            resolved_zone_codes=[z.zone_code for z in jurisdiction.matched_zones],
        )

        AuditLog.objects.create(
            complaint=complaint,
            actor_id="SYSTEM-AI-TRIAGE",
            actor_role="SYSTEM",
            action=f"AI_TRIAGE_{final_decision}",
            entity_type="TriageRun",
            entity_id=str(triage_run.run_id),
            payload={
                "source": "local_fallback",
                "confidence_score": clf_out.top_confidence,
                "gro_one_click_reassign_flag": clf_out.gro_one_click_reassign_flag,
                "primary_agency_code": triage_run.primary_agency_code,
                "resolved_zone_codes": triage_run.resolved_zone_codes,
            },
        )
        return triage_run
