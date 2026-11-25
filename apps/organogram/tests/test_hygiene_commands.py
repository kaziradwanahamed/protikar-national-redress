import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.organogram.models import DoptorOffice, DoptorSeat, RoleLevel, ServiceAreaPolygon


class GISImporterAndSeatAuditTests(TestCase):
    def test_import_gis_polygons_geojson_and_kml(self):
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "zone_code": "TEST-GEOJSON-W01",
                        "name_en": "Test Ward 01",
                        "bbs_geo_code": "30262601",
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [90.40, 23.78],
                                [90.42, 23.78],
                                [90.42, 23.80],
                                [90.40, 23.80],
                                [90.40, 23.78],
                            ]
                        ],
                    },
                }
            ],
        }
        kml = """<?xml version="1.0" encoding="UTF-8"?>
        <kml xmlns="http://www.opengis.net/kml/2.2">
          <Document>
            <Placemark>
              <name>Test KML Feeder 01</name>
              <ExtendedData>
                <Data name="zone_code"><value>TEST-KML-DESCO-01</value></Data>
                <Data name="bbs_geo_code"><value>30262602</value></Data>
              </ExtendedData>
              <Polygon>
                <outerBoundaryIs><LinearRing><coordinates>
                  90.40,23.78,0 90.41,23.78,0 90.41,23.79,0 90.40,23.79,0 90.40,23.78,0
                </coordinates></LinearRing></outerBoundaryIs>
              </Polygon>
            </Placemark>
          </Document>
        </kml>"""

        with tempfile.TemporaryDirectory() as tmpdir:
            gj_path = Path(tmpdir) / "wards.geojson"
            kml_path = Path(tmpdir) / "feeders.kml"
            gj_path.write_text(json.dumps(geojson), encoding="utf-8")
            kml_path.write_text(kml, encoding="utf-8")

            call_command("import_gis_polygons", str(gj_path), "--zone-type", "CITY_CORP_WARD", stdout=StringIO())
            call_command("import_gis_polygons", str(kml_path), "--zone-type", "DESCO_FEEDER", stdout=StringIO())

        self.assertTrue(ServiceAreaPolygon.objects.filter(zone_code="TEST-GEOJSON-W01").exists())
        self.assertTrue(ServiceAreaPolygon.objects.filter(zone_code="TEST-KML-DESCO-01").exists())

    def test_audit_doptor_seats_detects_vacant_without_additional_charge_and_orphans(self):
        office = DoptorOffice.objects.create(
            doptor_office_id="AUD-OFF-01",
            office_code="AUD-01",
            name_en="Audit Test Office",
            office_layer=DoptorOffice.OfficeLayer.CITY_CORP,
        )
        DoptorSeat.objects.create(
            doptor_seat_id="AUD-SEAT-VACANT-ORPHAN",
            office=office,
            designation_en="Field Engineer (Vacant & Orphan)",
            role_level=RoleLevel.FIELD_WORKER,
            is_vacant=True,
            additional_charge_seat=None,
            parent_seat=None,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = Path(tmpdir) / "seat_audit.json"
            with self.assertRaises(CommandError):
                call_command(
                    "audit_doptor_seats",
                    "--output",
                    str(out_json),
                    "--fail-on-error",
                    stdout=StringIO(),
                )
            report = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(len(report["vacant_without_additional_charge"]), 1)
            self.assertEqual(len(report["orphan_reporting_chains"]), 1)
