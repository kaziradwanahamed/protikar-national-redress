import json
from django.conf import settings
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings

from apps.complaints.models import AuditLog, Complaint
from apps.disaster.models import EmergencyCommandDispatch
from apps.esb.models import AgencyEndpoint, ESBDeliveryLog, OmnichannelIntakeRecord
from apps.esb.services.omnichannel import (
    CompactSMSParseError,
    OmnichannelIntakeService,
    parse_compact_2g_payload,
)
from apps.esb.services.tier1_webhooks import Tier1WebhookService, WebhookSignatureError
from apps.esb.services.tier2_rpa_bridge import Tier2RPABridgeService


@override_settings(ESB_PROVIDER_MODE="mock", KAFKA_PROVIDER_MODE="mock")
class ESBAndOmnichannelTests(TestCase):
    def setUp(self):
        self.complaint = Complaint.objects.create(
            citizen_uct_hash="f" * 64,
            raw_text_en="DESCO transformer outage in Banani.",
            urgency_tier=Complaint.UrgencyTier.P1,
            geo_point=Point(90.4043, 23.7937, srid=4326),
            admin_geo_code="30262619",
        )
        self.desco_ep = AgencyEndpoint.objects.create(
            agency_code="DESCO",
            agency_name="Dhaka Electric Supply Company",
            tier=AgencyEndpoint.IntegrationTier.TIER_1_REST_WEBHOOK,
            webhook_url="https://api.desco.org.bd/webhooks/grievance",
            hmac_secret="desco-shared-secret-2026",
        )
        self.legacy_ep = AgencyEndpoint.objects.create(
            agency_code="LEGACY_AGRI",
            agency_name="Legacy Agriculture Portal",
            tier=AgencyEndpoint.IntegrationTier.TIER_2_DB_RPA_BRIDGE,
            polling_enabled=True,
        )

    def test_tier1_outbound_and_signed_inbound_webhook(self):
        out_log = Tier1WebhookService.dispatch_outbound(
            agency_code="DESCO",
            event_type="COMPLAINT_ROUTED",
            complaint=self.complaint,
        )
        self.assertEqual(out_log.status, ESBDeliveryLog.Status.DELIVERED)

        inbound_payload = {
            "event_id": "evt-desco-991",
            "event_type": "CREW_DISPATCHED",
            "tracking_code": self.complaint.tracking_code,
        }
        raw_bytes = json.dumps(inbound_payload).encode("utf-8")
        good_sig = Tier1WebhookService.sign_payload(raw_bytes, self.desco_ep.hmac_secret)

        with self.assertRaises(WebhookSignatureError):
            Tier1WebhookService.receive_inbound(
                agency_code="DESCO",
                raw_bytes=raw_bytes,
                signature="tampered-signature",
                payload=inbound_payload,
            )

        in_log = Tier1WebhookService.receive_inbound(
            agency_code="DESCO",
            raw_bytes=raw_bytes,
            signature=good_sig,
            payload=inbound_payload,
        )
        self.assertEqual(in_log.status, ESBDeliveryLog.Status.ACKNOWLEDGED)
        self.assertTrue(AuditLog.verify_chain()[0])

    def test_tier2_rpa_bridge_10min_poll_cycle(self):
        res = Tier2RPABridgeService.run_poll_cycle()
        self.assertEqual(res["endpoints_polled"], 1)
        self.assertEqual(res["sync_events_logged"], 1)

    def test_compact_2g_sms_ussd_parser_under_140_bytes_and_fastlane(self):
        sms = "SOS#P1#24.8949,91.8687#Trapped on roof embankment breach"
        self.assertLessEqual(len(sms.encode("utf-8")), 140)
        res = OmnichannelIntakeService.ingest_compact_2g(
            sender_phone="+8801711999000",
            raw_payload=sms,
            channel=OmnichannelIntakeRecord.Channel.SMS_2G,
        )
        self.assertTrue(res["fastlane_triggered"])
        self.assertLessEqual(len(res["sms_reply"].encode("utf-8")), 140)
        self.assertEqual(EmergencyCommandDispatch.objects.count(), 1)

        ussd = "USSD*2*302626*WASA*Pipe burst"
        parsed_ussd = parse_compact_2g_payload(ussd)
        self.assertEqual(parsed_ussd.urgency_tier, "P2")
        self.assertEqual(parsed_ussd.agency_hint, "WASA")
        self.assertEqual(parsed_ussd.bbs_geo_code, "302626")

        with self.assertRaises(CompactSMSParseError):
            parse_compact_2g_payload("X" * 141)
