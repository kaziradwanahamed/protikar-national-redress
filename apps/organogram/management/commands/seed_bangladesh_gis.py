import hashlib
from datetime import timedelta

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.complaints.models import AuditLog, Complaint, ResolutionReport, TicketAssignment
from apps.organogram.models import DoptorOffice, DoptorSeat, RoleLevel, ServiceAreaPolygon


def _rect_multipolygon(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> MultiPolygon:
    """Build a closed WGS84 MultiPolygon bounding box for sample GIS zones."""
    poly = Polygon(
        (
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat),
        ),
        srid=4326,
    )
    return MultiPolygon(poly, srid=4326)


class Command(BaseCommand):
    help = (
        "Seeds sample Bangladesh administrative (BBS) and utility GIS polygons "
        "(DNCC/DSCC Wards, WASA MODS, DESCO/DPDC Feeders, RHD/LGED Roads) and "
        "Doptor offices/seats with escalation chains."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-sample-complaints",
            action="store_true",
            help="Also seed a sample Complaint, TicketAssignment, ResolutionReport, and SHA-256 AuditLog chain.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Bangladesh Doptor Organogram & GIS Zones..."))

        offices = self._seed_offices()
        seats = self._seed_seats(offices)
        areas = self._seed_service_areas(offices, seats)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {len(offices)} DoptorOffices, {len(seats)} DoptorSeats, "
                f"and {len(areas)} ServiceAreaPolygons."
            )
        )

        if options["with_sample_complaints"]:
            self._seed_sample_complaint_flow(offices, seats)

    def _seed_offices(self) -> dict[str, DoptorOffice]:
        office_specs = [
            {
                "doptor_office_id": "DOPTOR-OFF-LGRD-001",
                "office_code": "LGRD-MIN",
                "name_en": "Local Government Division (MoLGRD&C)",
                "name_bn": "স্থানীয় সরকার বিভাগ",
                "office_layer": DoptorOffice.OfficeLayer.MINISTRY,
                "ministry_code": "MIN-LGRD",
                "bbs_geo_code": "30",
                "parent": None,
            },
            {
                "doptor_office_id": "DOPTOR-OFF-DNCC-001",
                "office_code": "DNCC-HQ",
                "name_en": "Dhaka North City Corporation (DNCC)",
                "name_bn": "ঢাকা উত্তর সিটি কর্পোরেশন",
                "office_layer": DoptorOffice.OfficeLayer.CITY_CORP,
                "ministry_code": "MIN-LGRD",
                "bbs_geo_code": "3026",
                "parent": "DOPTOR-OFF-LGRD-001",
            },
            {
                "doptor_office_id": "DOPTOR-OFF-DSCC-001",
                "office_code": "DSCC-HQ",
                "name_en": "Dhaka South City Corporation (DSCC)",
                "name_bn": "ঢাকা দক্ষিণ সিটি কর্পোরেশন",
                "office_layer": DoptorOffice.OfficeLayer.CITY_CORP,
                "ministry_code": "MIN-LGRD",
                "bbs_geo_code": "3026",
                "parent": "DOPTOR-OFF-LGRD-001",
            },
            {
                "doptor_office_id": "DOPTOR-OFF-DWASA-004",
                "office_code": "DWASA-MODS-04",
                "name_en": "Dhaka WASA — MODS Zone 4 (Mirpur)",
                "name_bn": "ঢাকা ওয়াসা — মডস জোন ৪ (মিরপুর)",
                "office_layer": DoptorOffice.OfficeLayer.UTILITY,
                "ministry_code": "MIN-LGRD",
                "bbs_geo_code": "302648",
                "parent": "DOPTOR-OFF-LGRD-001",
            },
            {
                "doptor_office_id": "DOPTOR-OFF-DESCO-019",
                "office_code": "DESCO-GULSHAN",
                "name_en": "DESCO — Gulshan-Banani S&D Division",
                "name_bn": "ডেসকো — গুলশান-বনানী বিক্রয় ও বিতরণ বিভাগ",
                "office_layer": DoptorOffice.OfficeLayer.UTILITY,
                "ministry_code": "MIN-POWER",
                "bbs_geo_code": "302626",
                "parent": None,
            },
            {
                "doptor_office_id": "DOPTOR-OFF-DPDC-020",
                "office_code": "DPDC-MOTIJHEEL",
                "name_en": "DPDC — Motijheel NOCS Division",
                "name_bn": "ডিপিডিসি — মতিঝিল এনওসিএস বিভাগ",
                "office_layer": DoptorOffice.OfficeLayer.UTILITY,
                "ministry_code": "MIN-POWER",
                "bbs_geo_code": "302654",
                "parent": None,
            },
            {
                "doptor_office_id": "DOPTOR-OFF-RHD-DHK",
                "office_code": "RHD-DHK-DIV",
                "name_en": "Roads and Highways Department (RHD) — Dhaka Circle",
                "name_bn": "সড়ক ও জনপথ অধিদপ্তর — ঢাকা সার্কেল",
                "office_layer": DoptorOffice.OfficeLayer.ENGINEERING,
                "ministry_code": "MIN-RTHD",
                "bbs_geo_code": "3026",
                "parent": None,
            },
            {
                "doptor_office_id": "DOPTOR-OFF-LGED-SAV",
                "office_code": "LGED-SAVAR",
                "name_en": "LGED — Savar Upazila Engineering Office",
                "name_bn": "এলজিইডি — সাভার উপজেলা প্রকৌশলীর কার্যালয়",
                "office_layer": DoptorOffice.OfficeLayer.ENGINEERING,
                "ministry_code": "MIN-LGRD",
                "bbs_geo_code": "302672",
                "parent": "DOPTOR-OFF-LGRD-001",
            },
        ]

        created: dict[str, DoptorOffice] = {}
        for spec in office_specs:
            parent_obj = created.get(spec["parent"]) if spec["parent"] else None
            obj, _ = DoptorOffice.objects.update_or_create(
                doptor_office_id=spec["doptor_office_id"],
                defaults={
                    "office_code": spec["office_code"],
                    "name_en": spec["name_en"],
                    "name_bn": spec["name_bn"],
                    "office_layer": spec["office_layer"],
                    "ministry_code": spec["ministry_code"],
                    "bbs_geo_code": spec["bbs_geo_code"],
                    "parent_office": parent_obj,
                    "is_active": True,
                },
            )
            created[obj.doptor_office_id] = obj
        return created

    def _seed_seats(self, offices: dict[str, DoptorOffice]) -> dict[str, DoptorSeat]:
        seat_specs = [
            # DNCC Escalation Chain: FIELD_WORKER -> SUPERVISOR -> GRO -> APPELLATE
            ("SEAT-DNCC-APP-01", "DOPTOR-OFF-DNCC-001", "Chief Executive Officer (Appellate)", "প্রধান নির্বাহী কর্মকর্তা", RoleLevel.APPELLATE, None, "OFF-DNCC-1001", "Dr. M. Rahman"),
            ("SEAT-DNCC-GRO-19", "DOPTOR-OFF-DNCC-001", "Zonal Executive Officer — Zone 3 (GRO)", "আঞ্চলিক নির্বাহী কর্মকর্তা — অঞ্চল ৩", RoleLevel.GRO, "SEAT-DNCC-APP-01", "OFF-DNCC-1019", "N. Sultana"),
            ("SEAT-DNCC-SUP-19", "DOPTOR-OFF-DNCC-001", "Assistant Engineer — Ward 19", "সহকারী প্রকৌশলী — ওয়ার্ড ১৯", RoleLevel.SUPERVISOR, "SEAT-DNCC-GRO-19", "OFF-DNCC-2019", "T. Ahmed"),
            ("SEAT-DNCC-FW-19", "DOPTOR-OFF-DNCC-001", "Sub-Assistant Engineer — Ward 19", "উপ-সহকারী প্রকৌশলী — ওয়ার্ড ১৯", RoleLevel.FIELD_WORKER, "SEAT-DNCC-SUP-19", "OFF-DNCC-3019", "R. Karim"),
            # DSCC GRO
            ("SEAT-DSCC-APP-01", "DOPTOR-OFF-DSCC-001", "Secretary, DSCC (Appellate)", "সচিব, ডিএসসিসি", RoleLevel.APPELLATE, None, "OFF-DSCC-1001", "A. Hossain"),
            ("SEAT-DSCC-GRO-20", "DOPTOR-OFF-DSCC-001", "Zonal Executive Officer — Zone 1 (GRO)", "আঞ্চলিক নির্বাহী কর্মকর্তা — অঞ্চল ১", RoleLevel.GRO, "SEAT-DSCC-APP-01", "OFF-DSCC-1020", "F. Yasmin"),
            # Dhaka WASA MODS Zone 4
            ("SEAT-DWASA-GRO-04", "DOPTOR-OFF-DWASA-004", "Executive Engineer — MODS Zone 4 (GRO)", "নির্বাহী প্রকৌশলী — মডস জোন ৪", RoleLevel.GRO, None, "OFF-DWASA-401", "Engr. K. Islam"),
            # DESCO Gulshan Feeder
            ("SEAT-DESCO-GRO-19", "DOPTOR-OFF-DESCO-019", "Executive Engineer — Gulshan S&D (GRO)", "নির্বাহী প্রকৌশলী — গুলশান", RoleLevel.GRO, None, "OFF-DESCO-191", "Engr. S. Mahmud"),
            # DPDC Motijheel Feeder
            ("SEAT-DPDC-GRO-20", "DOPTOR-OFF-DPDC-020", "Executive Engineer — Motijheel NOCS (GRO)", "নির্বাহী প্রকৌশলী — মতিঝিল", RoleLevel.GRO, None, "OFF-DPDC-201", "Engr. H. Chowdhury"),
            # RHD & LGED
            ("SEAT-RHD-GRO-DHK", "DOPTOR-OFF-RHD-DHK", "Executive Engineer — RHD Dhaka (GRO)", "নির্বাহী প্রকৌশলী — সওজ ঢাকা", RoleLevel.GRO, None, "OFF-RHD-301", "Engr. M. Alam"),
            ("SEAT-LGED-GRO-SAV", "DOPTOR-OFF-LGED-SAV", "Upazila Engineer — Savar LGED (GRO)", "উপজেলা প্রকৌশলী — সাভার", RoleLevel.GRO, None, "OFF-LGED-721", "Engr. J. Uddin"),
        ]

        created: dict[str, DoptorSeat] = {}
        for seat_id, off_id, desig_en, desig_bn, role, parent_id, inc_id, inc_name in seat_specs:
            obj, _ = DoptorSeat.objects.update_or_create(
                doptor_seat_id=seat_id,
                defaults={
                    "office": offices[off_id],
                    "designation_en": desig_en,
                    "designation_bn": desig_bn,
                    "role_level": role,
                    "parent_seat": created.get(parent_id) if parent_id else None,
                    "incumbent_officer_id": inc_id,
                    "incumbent_name_en": inc_name,
                    "is_vacant": False,
                    "is_active": True,
                },
            )
            created[obj.doptor_seat_id] = obj
        return created

    def _seed_service_areas(
        self, offices: dict[str, DoptorOffice], seats: dict[str, DoptorSeat]
    ) -> dict[str, ServiceAreaPolygon]:
        area_specs = [
            # Administrative BBS Boundaries (Dhaka Division -> Dhaka District)
            (
                "BBS-DIV-30",
                ServiceAreaPolygon.ZoneType.BBS_DIVISION,
                "30",
                "Dhaka Division",
                "ঢাকা বিভাগ",
                None,
                "DOPTOR-OFF-LGRD-001",
                None,
                _rect_multipolygon(89.60, 23.00, 91.20, 24.60),
                {"level": "division"},
            ),
            (
                "BBS-DIST-3026",
                ServiceAreaPolygon.ZoneType.BBS_DISTRICT,
                "3026",
                "Dhaka District",
                "ঢাকা জেলা",
                "BBS-DIV-30",
                "DOPTOR-OFF-LGRD-001",
                None,
                _rect_multipolygon(90.05, 23.55, 90.55, 24.05),
                {"level": "district"},
            ),
            # City Corporation Wards
            (
                "DNCC-WARD-19",
                ServiceAreaPolygon.ZoneType.CITY_CORP_WARD,
                "30262619",
                "DNCC Ward 19 (Gulshan / Banani)",
                "ডিএনসিসি ওয়ার্ড ১৯ (গুলশান / বনানী)",
                "BBS-DIST-3026",
                "DOPTOR-OFF-DNCC-001",
                "SEAT-DNCC-GRO-19",
                _rect_multipolygon(90.400, 23.780, 90.425, 23.805),
                {"city_corp": "DNCC", "ward_no": 19},
            ),
            (
                "DSCC-WARD-20",
                ServiceAreaPolygon.ZoneType.CITY_CORP_WARD,
                "30265420",
                "DSCC Ward 20 (Segunbagicha / Motijheel)",
                "ডিএসসিসি ওয়ার্ড ২০ (সেগুনবাগিচা / মতিঝিল)",
                "BBS-DIST-3026",
                "DOPTOR-OFF-DSCC-001",
                "SEAT-DSCC-GRO-20",
                _rect_multipolygon(90.402, 23.725, 90.428, 23.745),
                {"city_corp": "DSCC", "ward_no": 20},
            ),
            # Utility Service Zones (overlapping admin boundaries)
            (
                "DWASA-MODS-Z04",
                ServiceAreaPolygon.ZoneType.WASA_MODS_ZONE,
                "302648",
                "Dhaka WASA MODS Zone 4 (Mirpur)",
                "ঢাকা ওয়াসা মডস জোন ৪ (মিরপুর)",
                "BBS-DIST-3026",
                "DOPTOR-OFF-DWASA-004",
                "SEAT-DWASA-GRO-04",
                _rect_multipolygon(90.345, 23.790, 90.385, 23.835),
                {"utility": "DWASA", "mods_zone": 4},
            ),
            (
                "DESCO-FDR-GUL-01",
                ServiceAreaPolygon.ZoneType.DESCO_FEEDER,
                "30262619",
                "DESCO 11kV Gulshan-Banani Feeder 01",
                "ডেসকো গুলশান-বনানী ফিডার ০১",
                "BBS-DIST-3026",
                "DOPTOR-OFF-DESCO-019",
                "SEAT-DESCO-GRO-19",
                _rect_multipolygon(90.398, 23.778, 90.426, 23.808),
                {"utility": "DESCO", "voltage_kv": 11},
            ),
            (
                "DPDC-FDR-MTJ-02",
                ServiceAreaPolygon.ZoneType.DPDC_FEEDER,
                "30265420",
                "DPDC 11kV Motijheel Commercial Feeder 02",
                "ডিপিডিসি মতিঝিল ফিডার ০২",
                "BBS-DIST-3026",
                "DOPTOR-OFF-DPDC-020",
                "SEAT-DPDC-GRO-20",
                _rect_multipolygon(90.405, 23.722, 90.430, 23.744),
                {"utility": "DPDC", "voltage_kv": 11},
            ),
            # Road Corridors (RHD & LGED)
            (
                "RHD-N1-JATRABARI-KANCHPUR",
                ServiceAreaPolygon.ZoneType.RHD_ROAD,
                "3026",
                "RHD N1 Dhaka-Chattogram Highway Corridor (Jatrabari–Kanchpur)",
                "সওজ এন-১ ঢাকা-চট্টগ্রাম মহাসড়ক",
                "BBS-DIST-3026",
                "DOPTOR-OFF-RHD-DHK",
                "SEAT-RHD-GRO-DHK",
                _rect_multipolygon(90.435, 23.695, 90.525, 23.720),
                {"agency": "RHD", "highway_code": "N1"},
            ),
            (
                "LGED-SAVAR-ASHULIA-UZR",
                ServiceAreaPolygon.ZoneType.LGED_ROAD,
                "302672",
                "LGED Savar–Ashulia Upazila Road Corridor",
                "এলজিইডি সাভার-আশুলিয়া উপজেলা সড়ক",
                "BBS-DIST-3026",
                "DOPTOR-OFF-LGED-SAV",
                "SEAT-LGED-GRO-SAV",
                _rect_multipolygon(90.250, 23.860, 90.340, 23.920),
                {"agency": "LGED", "road_class": "Upazila Road"},
            ),
        ]

        created: dict[str, ServiceAreaPolygon] = {}
        for zcode, ztype, bbs, name_en, name_bn, parent_z, off_id, seat_id, geom, meta in area_specs:
            obj, _ = ServiceAreaPolygon.objects.update_or_create(
                zone_code=zcode,
                defaults={
                    "zone_type": ztype,
                    "bbs_geo_code": bbs,
                    "name_en": name_en,
                    "name_bn": name_bn,
                    "parent_area": created.get(parent_z) if parent_z else None,
                    "primary_office": offices.get(off_id),
                    "default_gro_seat": seats.get(seat_id) if seat_id else None,
                    "geom": geom,
                    "metadata": meta,
                    "is_active": True,
                },
            )
            created[obj.zone_code] = obj
        return created

    def _seed_sample_complaint_flow(self, offices, seats):
        if Complaint.objects.filter(tracking_code="BD-2026-DHK-0094821").exists():
            self.stdout.write("Sample complaint BD-2026-DHK-0094821 already exists; skipping.")
            return

        uct_hash = hashlib.sha256(b"demo-citizen-token-dhaka-01").hexdigest()
        complaint = Complaint.objects.create(
            tracking_code="BD-2026-DHK-0094821",
            citizen_uct_hash=uct_hash,
            is_anonymous=False,
            raw_text_bn="গুলশান-২ রোড ৪৫ এর সামনে রাস্তার লাইট ৩ দিন ধরে নষ্ট এবং জলাবদ্ধতা তৈরি হয়েছে।",
            raw_text_en="Streetlights near Gulshan-2 Road 45 have been out for 3 days with waterlogging.",
            ai_category_code="URBAN_INFRA.STREETLIGHT_DRAINAGE",
            ai_confidence=0.94,
            urgency_tier=Complaint.UrgencyTier.P2,
            geo_point=Point(90.4143, 23.7925, srid=4326),
            admin_geo_code="30262619",
            h3_hex_index="893d808c32fffff",
            status=Complaint.ComplaintStatus.RESOLVED_PENDING,
            sla_deadline_at=timezone.now() + timedelta(hours=24),
        )

        TicketAssignment.objects.create(
            complaint=complaint,
            doptor_office_id="DOPTOR-OFF-DNCC-001",
            doptor_seat_id="SEAT-DNCC-GRO-19",
            assigned_officer_id="OFF-DNCC-1019",
            role_level=RoleLevel.GRO,
            due_at=timezone.now() + timedelta(hours=20),
            is_active=True,
        )

        ResolutionReport.objects.create(
            complaint=complaint,
            submitted_by_seat="SEAT-DNCC-FW-19",
            work_summary="Replaced faulty LED streetlamp ballast and cleared catch-basin drainage silt.",
            after_photo_urls=["https://minio.local/grievance-media-encrypted/resolutions/demo-after-1.jpg"],
            gps_verified_dist_m=14.2,
            citizen_verdict=ResolutionReport.CitizenVerdict.PENDING,
        )

        AuditLog.objects.create(
            complaint=complaint,
            actor_id="SYSTEM-AI-TRIAGE",
            actor_role="SYSTEM",
            action="COMPLAINT_CREATED_AND_TRIAGED",
            entity_type="Complaint",
            entity_id=str(complaint.complaint_id),
            payload={"tracking_code": complaint.tracking_code, "urgency_tier": "P2"},
        )
        AuditLog.objects.create(
            complaint=complaint,
            actor_id="OFF-DNCC-1019",
            actor_seat_id="SEAT-DNCC-GRO-19",
            actor_role=RoleLevel.GRO,
            action="TICKET_ASSIGNED",
            entity_type="TicketAssignment",
            entity_id=str(complaint.complaint_id),
            payload={"doptor_seat_id": "SEAT-DNCC-GRO-19"},
        )

        is_valid, checked, broken = AuditLog.verify_chain()
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded sample complaint {complaint.tracking_code}; "
                f"AuditLog chain valid={is_valid} (checked={checked}, broken={broken})."
            )
        )
