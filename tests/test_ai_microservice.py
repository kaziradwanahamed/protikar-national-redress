"""
Unit & Integration Tests for Part 10: Standalone FastAPI AI Microservice & Django Integration.
Verifies:
  (a) >=85%, 60%-84%, and <60% confidence routing behaviors
  (b) Compound multi-department splitting with step_order 1 -> 2 -> 3 dependency order
  (c) Bangla Geo-NER + road ownership hints + P1 life-safety detection
  (d) Django FastAPIAITriageClient integration & local fallback resilience
"""

from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point

from ai_service.pipelines.asr import BanglaDialectASRPipeline
from ai_service.pipelines.classifier import HierarchicalDepartmentClassifier
from ai_service.pipelines.compound_splitter import CompoundSplitterPipeline
from ai_service.pipelines.geo_ner import BanglaGeoNERPipeline
from ai_service.pipelines.vision_ocr import VisionOCRPipeline
from apps.ai_triage.models import SubTicketDependency, TriageRun
from apps.ai_triage.services.pipeline import AITriageOrchestrator
from apps.complaints.models import Complaint


def test_ai_classifier_confidence_thresholds_85_60_below_60():
    clf = HierarchicalDepartmentClassifier()

    # >= 85%: auto_route = True
    high = clf.classify(text_en="DESCO snapped electric pole with live wire sparking!")
    assert high["confidence"] >= 0.85
    assert high["auto_route"] is True
    assert high["needs_gro_review"] is False
    assert high["clarifying_questions"] == []

    # 60%–84%: needs_gro_review = True
    mid = clf.classify(text_en="There is a pothole on the road.", override_confidence=0.72)
    assert 0.60 <= mid["confidence"] < 0.85
    assert mid["auto_route"] is False
    assert mid["needs_gro_review"] is True

    # < 60%: returns 1-2 Bangla & English clarifying questions
    low = clf.classify(text_en="Please help with an issue near my home.")
    assert low["confidence"] < 0.60
    assert low["auto_route"] is False
    assert len(low["clarifying_questions"]) == 2
    assert "en" in low["clarifying_questions"][0] and "bn" in low["clarifying_questions"][0]


def test_ai_compound_splitter_dependency_sequence_1_2_3():
    clf = HierarchicalDepartmentClassifier()
    splitter = CompoundSplitterPipeline()
    narrative = (
        "Burst WASA water pipe flooded the road, snapped a DESCO electric pole, "
        "and DNCC garbage is piling up."
    )
    out = clf.classify(text_en=narrative)
    is_compound, plan = splitter.build_plan(predictions=out["predictions"], narrative_en=narrative)

    assert is_compound is True
    assert len(plan) == 3
    assert [s["step_order"] for s in plan] == [1, 2, 3]
    assert plan[0]["agency_code"] == "DESCO"
    assert plan[0]["depends_on_step"] is None
    assert plan[1]["agency_code"] == "WASA"
    assert plan[1]["depends_on_step"] == 1
    assert plan[2]["agency_code"] == "DNCC"
    assert plan[2]["depends_on_step"] == 2


def test_bangla_geo_ner_road_ownership_and_p1_life_safety_filter():
    geo = BanglaGeoNERPipeline()
    res = geo.analyze(
        text_bn="সিলেট বন্যায় ছাদে আটকা পড়েছি, বাঁধ ভেঙে পানিতে বিদ্যুতের তার ছিঁড়ে পড়েছে।",
        text_en="Embankment breach and live wire in water on LGED upazila road in Sylhet.",
    )
    assert res["division"] == "Sylhet"
    assert res["bbs_geo_code"] == "6091"
    assert res["road_ownership_hint"] == "LGED_RURAL_ROAD"
    assert res["is_life_safety_p1"] is True
    assert "ছাদে আটকা" in res["matched_rescue_keywords"]
    assert "embankment breach" in res["matched_rescue_keywords"]


def test_asr_dialects_and_bangla_ocr_pipeline():
    asr = BanglaDialectASRPipeline().transcribe("https://minio.local/voice/sylhet_sos.ogg", hint_dialect="sylheti")
    assert asr["detected_dialect"] == "sylheti"
    assert "ছাদে আটকা" in asr["transcript_bn"]

    ocr = VisionOCRPipeline().analyze(
        ["https://minio.local/photos/transformer_receipt.jpg"],
        context_text="Receipt: রসিদ-২০২৬৪৫ EGP-2026-998877 DESCO-AB1234",
    )
    assert ocr["evidence_valid"] is True
    assert ocr["hazard_severity"] == "CRITICAL"
    assert ocr["extracted_refs"]["egp_tender_id"] == "2026-998877"
    assert ocr["extracted_refs"]["desco_account"] == "AB1234"


@pytest.mark.django_db
def test_django_to_fastapi_integration_and_compound_ticket_creation(ndc_org_fixture):
    env = ndc_org_fixture
    mock_fastapi_response = {
        "asr": None,
        "vision_ocr": {"evidence_valid": True, "hazard_severity": "CRITICAL", "evidence_labels": ["burst_water_pipe"], "extracted_refs": {}},
        "predictions": [
            {"ministry_code": "MIN-POWER", "ministry_name": "Power", "agency_code": "DESCO", "agency_name": "DESCO", "category_code": "POWER.SNAPPED_POLE_OUTAGE", "zone_type": "DESCO_FEEDER", "urgency_tier": "P1", "confidence": 0.94, "step_order": 1},
            {"ministry_code": "MIN-LGRD", "ministry_name": "LGRD", "agency_code": "WASA", "agency_name": "WASA", "category_code": "WATER.BURST_PIPE_SUPPLY", "zone_type": "WASA_MODS_ZONE", "urgency_tier": "P2", "confidence": 0.91, "step_order": 2},
        ],
        "primary_ministry_code": "MIN-POWER",
        "primary_agency_code": "DESCO",
        "primary_category_code": "POWER.SNAPPED_POLE_OUTAGE",
        "confidence": 0.94,
        "auto_route": True,
        "needs_gro_review": False,
        "clarifying_questions": [],
        "is_compound": True,
        "child_subtickets": [],
        "geo_ner": {"bbs_geo_code": "30262619", "extracted_entities": ["Gulshan"], "is_life_safety_p1": True},
        "is_life_safety_p1": True,
        "recommended_urgency_tier": "P1",
        "taxonomy_coverage": {"ministries_divisions": 58, "directorates_agencies": 356},
    }

    complaint = Complaint.objects.create(
        citizen_uct_hash=env["profile"].pseudonymous_public_hash,
        raw_text_en="Snapped DESCO pole and burst WASA pipe in Gulshan!",
        geo_point=Point(90.4143, 23.7925, srid=4326),
    )

    with patch("apps.ai_triage.services.ai_client.FastAPIAITriageClient.analyze", return_value=mock_fastapi_response):
        run = AITriageOrchestrator.process_complaint(complaint=complaint)

    assert run.routing_decision == TriageRun.RoutingDecision.COMPOUND_SPLIT
    assert Complaint.objects.filter(parent_case=complaint).count() == 2
    assert SubTicketDependency.objects.filter(parent_case=complaint).count() == 1
