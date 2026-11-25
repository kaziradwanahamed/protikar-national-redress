from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.test import TestCase, override_settings

from apps.complaints.models import AuditLog, Complaint
from apps.disaster.models import CrisisZone, EmergencyCommandDispatch
from apps.disaster.services.circuit_breaker import DisasterCircuitBreakerService
from apps.disaster.services.h3_surge_pipeline import H3SurgeIngestionService
from apps.organogram.models import ServiceAreaPolygon


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


@override_settings(KAFKA_PROVIDER_MODE="mock", DISASTER_SURGE_MULTIPLIER=5.0)
class DisasterSurgeCircuitBreakerTests(TestCase):
    def setUp(self):
        self.polygon = ServiceAreaPolygon.objects.create(
            zone_code="DIS-TEST-SYL-01",
            zone_type=ServiceAreaPolygon.ZoneType.BBS_DISTRICT,
            bbs_geo_code="6091",
            name_en="Sylhet Flood Basin",
            geom=_box(91.70, 24.80, 92.00, 25.05),
        )
        self.p3_inside = Complaint.objects.create(
            citizen_uct_hash="d" * 64,
            raw_text_en="Routine streetlight replacement request.",
            urgency_tier=Complaint.UrgencyTier.P3,
            geo_point=Point(91.86, 24.89, srid=4326),
            status=Complaint.ComplaintStatus.ROUTED,
        )
        self.p1_inside = Complaint.objects.create(
            citizen_uct_hash="e" * 64,
            raw_text_en="Live wire in water!",
            urgency_tier=Complaint.UrgencyTier.P1,
            geo_point=Point(91.87, 24.90, srid=4326),
            status=Complaint.ComplaintStatus.ROUTED,
        )

    def test_5x_velocity_circuit_breaker_activates_crisis_and_freezes_p3_p4_only(self):
        # baseline=1/hr -> 5x threshold = 5; 6th hit trips circuit breaker
        for i in range(6):
            res = DisasterCircuitBreakerService.record_polygon_hit(
                zone_code="DIS-TEST-SYL-01", baseline_per_hour=1.0
            )
        self.assertTrue(res["circuit_breaker_tripped"])
        self.assertIsNotNone(res["crisis_id"])

        self.p3_inside.refresh_from_db()
        self.p1_inside.refresh_from_db()
        self.assertEqual(self.p3_inside.status, Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED)
        self.assertEqual(self.p1_inside.status, Complaint.ComplaintStatus.ROUTED)
        self.assertTrue(AuditLog.verify_chain()[0])

    def test_h3_res8_surge_ingest_and_p1_life_safety_fastlane(self):
        crisis = DisasterCircuitBreakerService.activate_crisis_zone(
            crisis_code="CYC-REMAL-2026",
            name_en="Cyclone Emergency Zone",
            geom=self.polygon.geom,
            trigger_source=CrisisZone.TriggerSource.MODMR_TOGGLE,
            activated_by_seat="SEAT-MODMR-SEC",
        )
        result = H3SurgeIngestionService.ingest_surge_report(
            lat=24.8949,
            lon=91.8687,
            message="Family trapped on roof with medical emergency and embankment breach!",
            citizen_phone="+8801711000888",
            crisis_zone=crisis,
        )
        self.assertTrue(result.fastlane_triggered)
        self.assertIn("trapped on roof", result.matched_rescue_keywords)
        self.assertIn("medical emergency", result.matched_rescue_keywords)
        self.assertEqual(EmergencyCommandDispatch.objects.count(), 1)

        heatmap = H3SurgeIngestionService.get_live_h3_heatmap(crisis_id=str(crisis.crisis_id))
        self.assertGreaterEqual(len(heatmap), 1)
        self.assertEqual(heatmap[0]["h3_res8_index"], result.h3_res8_index)
