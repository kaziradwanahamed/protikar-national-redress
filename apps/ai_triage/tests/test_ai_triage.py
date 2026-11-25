from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase, override_settings

from apps.ai_triage.models import (
    MasterIncidentSubscription,
    SubTicketDependency,
    TriageRun,
)
from apps.ai_triage.services.classifier import HierarchicalMultiLabelClassifier
from apps.ai_triage.services.deduplicator import SpatialDeduplicationService
from apps.ai_triage.services.geo_resolver import PostGISJurisdictionResolver
from apps.ai_triage.services.multimodal import MultimodalPreprocessor, normalize_bangla_digits
from apps.ai_triage.services.pipeline import AITriageOrchestrator
from apps.ai_triage.services.splitter import CompoundComplaintSplitter
from apps.complaints.models import AuditLog, Complaint
from apps.organogram.models import DoptorOffice, DoptorSeat, RoleLevel, ServiceAreaPolygon


def _box(min_lon, min_lat, max_lon, max_lat):
    return MultiPolygon(
        Polygon(
            (
                (min_lon, min_lat),
                (max_lon, min_lat),
                (max_lon, max_lat),
                (min_lon, max_lat),
                (min_lon, min_lat),
            ),
            srid=4326,
        ),
        srid=4326,
    )


@override_settings(AI_PROVIDER_MODE="mock")
class AITriagePipelineTests(TestCase):
    def setUp(self):
        self.dncc_off = DoptorOffice.objects.create(
            doptor_office_id="AI-OFF-DNCC",
            office_code="AI-DNCC",
            name_en="DNCC",
            office_layer=DoptorOffice.OfficeLayer.CITY_CORP,
        )
        self.wasa_off = DoptorOffice.objects.create(
            doptor_office_id="AI-OFF-WASA",
            office_code="AI-WASA",
            name_en="Dhaka WASA",
            office_layer=DoptorOffice.OfficeLayer.UTILITY,
        )
        self.desco_off = DoptorOffice.objects.create(
            doptor_office_id="AI-OFF-DESCO",
            office_code="AI-DESCO",
            name_en="DESCO",
            office_layer=DoptorOffice.OfficeLayer.UTILITY,
        )
        self.dncc_seat = DoptorSeat.objects.create(
            doptor_seat_id="AI-SEAT-DNCC-GRO",
            office=self.dncc_off,
            designation_en="DNCC GRO",
            role_level=RoleLevel.GRO,
            incumbent_officer_id="EMP-DNCC-1",
        )
        self.wasa_seat = DoptorSeat.objects.create(
            doptor_seat_id="AI-SEAT-WASA-GRO",
            office=self.wasa_off,
            designation_en="WASA GRO",
            role_level=RoleLevel.GRO,
            incumbent_officer_id="EMP-WASA-1",
        )
        self.desco_seat = DoptorSeat.objects.create(
            doptor_seat_id="AI-SEAT-DESCO-GRO",
            office=self.desco_off,
            designation_en="DESCO GRO",
            role_level=RoleLevel.GRO,
            incumbent_officer_id="EMP-DESCO-1",
        )

        # Overlapping Gulshan polygons (City Corp Ward + WASA MODS + DESCO Feeder)
        box = _box(90.400, 23.780, 90.430, 23.810)
        ServiceAreaPolygon.objects.create(
            zone_code="AI-DNCC-W19",
            zone_type=ServiceAreaPolygon.ZoneType.CITY_CORP_WARD,
            bbs_geo_code="30262619",
            name_en="DNCC Ward 19",
            primary_office=self.dncc_off,
            default_gro_seat=self.dncc_seat,
            geom=box,
        )
        ServiceAreaPolygon.objects.create(
            zone_code="AI-WASA-Z01",
            zone_type=ServiceAreaPolygon.ZoneType.WASA_MODS_ZONE,
            bbs_geo_code="30262619",
            name_en="WASA Gulshan MODS",
            primary_office=self.wasa_off,
            default_gro_seat=self.wasa_seat,
            geom=box,
        )
        ServiceAreaPolygon.objects.create(
            zone_code="AI-DESCO-F01",
            zone_type=ServiceAreaPolygon.ZoneType.DESCO_FEEDER,
            bbs_geo_code="30262619",
            name_en="DESCO Gulshan Feeder",
            primary_office=self.desco_off,
            default_gro_seat=self.desco_seat,
            geom=box,
        )

    def test_multimodal_bangla_asr_and_vlm_ocr_reference_extraction(self):
        self.assertEqual(normalize_bangla_digits("রসিদ-২০২৬৯৯"), "রসিদ-202699")
        bn, en, asr, vlm = MultimodalPreprocessor().run(
            raw_text_en="Receipt: CHL-99482 EGP-2026-123456 DESCO-AB1234",
            voice_audio_url="https://minio.local/voice/sylhet_pipe_report.ogg",
            photo_urls=["https://minio.local/photos/burst_pipe_road.jpg"],
        )
        self.assertEqual(asr.detected_dialect, "sylheti")
        self.assertTrue(vlm.evidence_valid)
        self.assertIn("egp_tender_id", vlm.extracted_refs)
        self.assertIn("desco_account", vlm.extracted_refs)
        self.assertIn("ওয়াসা", bn)
        self.assertIn("WASA", en)

    def test_hierarchical_classifier_confidence_bands(self):
        clf = HierarchicalMultiLabelClassifier()
        # >=85%: Auto-route
        high = clf.classify(text_en="DESCO electric pole snapped and live wire sparking!")
        self.assertEqual(high.routing_decision, TriageRun.RoutingDecision.AUTO_ROUTED)
        self.assertFalse(high.gro_one_click_reassign_flag)

        # 60-84%: GRO 1-click reassign flag
        mid = clf.classify(text_en="Need help with pothole.", override_confidence=0.72)
        self.assertEqual(mid.routing_decision, TriageRun.RoutingDecision.GRO_REASSIGN_FLAGGED)
        self.assertTrue(mid.gro_one_click_reassign_flag)

        # <60%: Clarifying questions returned
        low = clf.classify(text_en="Something is wrong near my house.")
        self.assertEqual(low.routing_decision, TriageRun.RoutingDecision.CLARIFICATION_REQUIRED)
        self.assertGreaterEqual(len(low.clarifying_questions), 1)

    def test_compound_splitter_spawns_dependent_subtickets_in_engineering_order(self):
        compound = Complaint.objects.create(
            citizen_uct_hash="c" * 64,
            raw_text_en="Burst WASA water pipe, snapped DESCO electric pole, and damaged DNCC road pothole in Gulshan!",
            geo_point=Point(90.4143, 23.7925, srid=4326),
        )
        run = AITriageOrchestrator.process_complaint(complaint=compound)
        self.assertEqual(run.routing_decision, TriageRun.RoutingDecision.COMPOUND_SPLIT)

        children = list(Complaint.objects.filter(parent_case=compound))
        self.assertEqual(len(children), 3)

        deps = list(SubTicketDependency.objects.filter(parent_case=compound).order_by("sequence_order"))
        self.assertGreaterEqual(len(deps), 2)
        # Phase 1 (DESCO) must block Phase 2 (WASA), which blocks Phase 3 (CITY_CORP)
        desco_ticket = next(c for c in children if c.ai_category_code.startswith("POWER"))
        wasa_ticket = next(c for c in children if c.ai_category_code.startswith("WATER"))
        road_ticket = next(c for c in children if c.ai_category_code.startswith("URBAN_INFRA"))

        self.assertEqual(desco_ticket.status, Complaint.ComplaintStatus.ROUTED)
        self.assertEqual(wasa_ticket.status, Complaint.ComplaintStatus.SUBMITTED)
        self.assertEqual(road_ticket.status, Complaint.ComplaintStatus.SUBMITTED)

        # Completing DESCO releases WASA
        released_1 = CompoundComplaintSplitter.release_dependent_subtickets(desco_ticket)
        self.assertEqual([c.complaint_id for c in released_1], [wasa_ticket.complaint_id])
        # Completing WASA releases City Corp road repair
        released_2 = CompoundComplaintSplitter.release_dependent_subtickets(wasa_ticket)
        self.assertEqual([c.complaint_id for c in released_2], [road_ticket.complaint_id])

    def test_spatial_dedup_within_200m_clusters_and_boosts_priority(self):
        c1 = Complaint.objects.create(
            citizen_uct_hash="u1" + "0" * 62,
            raw_text_en="Large pothole on Gulshan road.",
            ai_category_code="URBAN_INFRA.ROAD_DRAINAGE_LIGHT",
            urgency_tier=Complaint.UrgencyTier.P3,
            geo_point=Point(90.4143, 23.7925, srid=4326),
            status=Complaint.ComplaintStatus.ROUTED,
        )
        SpatialDeduplicationService.deduplicate_and_cluster(complaint=c1)

        # Two more unique citizens within ~30m -> hits 3 unique citizens -> boosts P3 -> P2
        for idx, offset in enumerate((0.0001, 0.0002), start=2):
            dup = Complaint.objects.create(
                citizen_uct_hash=f"u{idx}" + "0" * 62,
                raw_text_en="Same pothole on Gulshan road!",
                ai_category_code="URBAN_INFRA.ROAD_DRAINAGE_LIGHT",
                urgency_tier=Complaint.UrgencyTier.P3,
                geo_point=Point(90.4143 + offset, 23.7925, srid=4326),
                status=Complaint.ComplaintStatus.SUBMITTED,
            )
            res = SpatialDeduplicationService.deduplicate_and_cluster(complaint=dup)
            self.assertTrue(res.is_duplicate)
            self.assertEqual(res.master_incident.complaint_id, c1.complaint_id)

        c1.refresh_from_db()
        self.assertEqual(c1.urgency_tier, Complaint.UrgencyTier.P2)
        self.assertEqual(MasterIncidentSubscription.objects.filter(master_complaint=c1).count(), 3)
        self.assertTrue(AuditLog.verify_chain()[0])
