import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings

from apps.complaints.models import Complaint


@override_settings(AI_PROVIDER_MODE="mock")
class ShadowRoutingSimulatorTests(TestCase):
    def test_shadow_routing_replays_in_zero_write_dry_run_and_exports_reports(self):
        sample = [
            {
                "id": "HIST-001",
                "text_en": "Dhaka WASA water pipe burst in Gulshan.",
                "lat": 23.7925,
                "lon": 90.4143,
                "expected_agency_code": "DWASA",
            },
            {
                "id": "HIST-002",
                "text_en": "DESCO snapped electric pole with sparking wire.",
                "lat": 23.7937,
                "lon": 90.4043,
                "expected_agency_code": "DWASA",  # intentional mismatch to verify misroute detection
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "historical_grs.json"
            csv_out = Path(tmpdir) / "audit.csv"
            json_out = Path(tmpdir) / "summary.json"
            src.write_text(json.dumps(sample), encoding="utf-8")

            call_command(
                "run_shadow_routing",
                "--file",
                str(src),
                "--output-csv",
                str(csv_out),
                "--output-json",
                str(json_out),
                stdout=StringIO(),
            )

            self.assertEqual(Complaint.objects.count(), 0)
            self.assertTrue(csv_out.exists())
            summary = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(summary["total_replayed"], 2)
            self.assertEqual(summary["matched_count"], 1)
            self.assertEqual(summary["misroute_count"], 1)
            self.assertEqual(summary["accuracy_pct"], 50.0)
