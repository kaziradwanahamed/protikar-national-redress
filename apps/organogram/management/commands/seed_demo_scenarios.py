"""
Idempotent Rich Bangladesh Scenario Seeder (`python manage.py seed_demo_scenarios`).

Populates:
  - 8 ready-to-use demo accounts across every role (password: Demo@2026)
  - 27 realistic complaints covering every statutory workflow, AI triage,
    spatial clustering, whistleblower Vault, and disaster surge feature
  - Valid SHA-256 hash-chained AuditLog entries across all seeded transitions
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

from django.contrib.gis.geos import MultiPolygon, Point, Polygon
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.demo_roles import DEMO_PASSWORD
from apps.accounts.models import CitizenProfile, User
from apps.accounts.services.oidc_providers import CitizenIdentityService
from apps.accounts.services.vault_envelope import WhistleblowerPrivacyService
from apps.ai_triage.models import (
    MasterIncidentSubscription,
    SubTicketDependency,
    TriageRun,
)
from apps.complaints.models import AuditLog, Complaint, ResolutionReport, TicketAssignment
from apps.disaster.models import CrisisZone, EmergencyCommandDispatch
from apps.disaster.services.h3_surge_pipeline import H3SurgeIngestionService, latlng_to_h3_res8
from apps.organogram.models import DoptorOffice, DoptorSeat, RoleLevel, ServiceAreaPolygon
from apps.workflow.models import (
    ArbitrationCase,
    CapitalMilestone,
    DDCCAgendaItem,
    EscalationEvent,
    WorkflowTracker,
)


def _box(min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> MultiPolygon:
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


class Command(BaseCommand):
    help = (
        "Idempotently seeds 8 Bangladesh demo role accounts (Demo@2026), 27 realistic "
        "statutory grievance scenarios, disaster surge H3 cells, and SHA-256 AuditLog entries."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding Bangladesh Demo Scenarios (Part 9)..."))
        call_command("seed_bangladesh_gis", verbosity=0)

        offices, seats = self._seed_demo_organogram()
        users, profiles = self._seed_demo_accounts()

        created_complaints = 0
        created_complaints += self._seed_compound_mirpur_case(profiles["citizen_demo"])
        created_complaints += self._seed_200m_hotspot_cluster_mirpur(profiles["citizen_demo"])
        created_complaints += self._seed_two_key_verification_cases(profiles["citizen_demo"])
        created_complaints += self._seed_governance_safeguard_cases(profiles["citizen_demo"])
        created_complaints += self._seed_whistleblower_vault_case(profiles["whistleblower_demo"])
        created_complaints += self._seed_disaster_surge_sylhet_feni(profiles["citizen_demo"])

        is_valid, checked, broken = AuditLog.verify_chain()
        if not is_valid:
            raise RuntimeError(f"AuditLog SHA-256 chain verification failed at {broken}!")

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo scenarios ready: 8 accounts (password={DEMO_PASSWORD}), "
                f"{Complaint.objects.count()} total complaints ({created_complaints} newly created), "
                f"AuditLog chain intact ({checked} entries)."
            )
        )

    def _seed_demo_organogram(self):
        office_specs = [
            ("DOPTOR-OFF-DNCC-Z2", "DNCC-Z2", "DNCC Zone-2 (Mirpur)", "ডিএনসিসি অঞ্চল-২ (মিরপুর)", DoptorOffice.OfficeLayer.CITY_CORP, "302648"),
            ("DOPTOR-OFF-DPDC-MRP", "DPDC-MIRPUR", "DPDC Mirpur NOCS Division", "ডিপিডিসি মিরপুর বিভাগ", DoptorOffice.OfficeLayer.UTILITY, "302648"),
            ("DOPTOR-OFF-DC-DHK", "DC-DHAKA", "Office of the Deputy Commissioner, Dhaka", "জেলা প্রশাসকের কার্যালয়, ঢাকা", DoptorOffice.OfficeLayer.DISTRICT, "3026"),
            ("DOPTOR-OFF-CABINET", "CABINET-CELL", "Cabinet Division National Command Cell", "মন্ত্রিপরিষদ বিভাগ কমান্ড সেল", DoptorOffice.OfficeLayer.MINISTRY, "30"),
            ("DOPTOR-OFF-UDC-SAV", "UDC-SAVAR", "Savar Union Digital Center (UDC)", "সাভার ইউনিয়ন ডিজিটাল সেন্টার", DoptorOffice.OfficeLayer.UPAZILA, "302672"),
        ]
        offices = {}
        for off_id, code, name_en, name_bn, layer, bbs in office_specs:
            obj, _ = DoptorOffice.objects.update_or_create(
                doptor_office_id=off_id,
                defaults={
                    "office_code": code,
                    "name_en": name_en,
                    "name_bn": name_bn,
                    "office_layer": layer,
                    "bbs_geo_code": bbs,
                    "is_active": True,
                },
            )
            offices[code] = obj

        seat_specs = [
            ("SEAT-CABINET-CMD-01", "CABINET-CELL", "Secretary, Cabinet Command Cell", RoleLevel.APPELLATE, None, "EMP-CAB-001", "Dr. A. Salam"),
            ("SEAT-DC-DHAKA-ARB", "DC-DHAKA", "Deputy Commissioner, Dhaka (Arbitrator)", RoleLevel.APPELLATE, "SEAT-CABINET-CMD-01", "EMP-DC-DHK", "M. Hossain, BCS"),
            ("SEAT-DNCC-Z2-GRO", "DNCC-Z2", "Zonal Executive Officer — DNCC Zone-2 (GRO / অনিক)", RoleLevel.GRO, "SEAT-DC-DHAKA-ARB", "EMP-DNCC-Z2", "S. Akter"),
            ("SEAT-DPDC-MIRPUR-SUP", "DPDC-MIRPUR", "Executive Engineer — DPDC Mirpur (Supervisor)", RoleLevel.SUPERVISOR, "SEAT-DC-DHAKA-ARB", "EMP-DPDC-SUP", "Engr. R. Islam"),
            ("SEAT-DPDC-MIRPUR-FW", "DPDC-MIRPUR", "Sub-Assistant Engineer — Mirpur Sub-Division", RoleLevel.FIELD_WORKER, "SEAT-DPDC-MIRPUR-SUP", "EMP-DPDC-FW1", "K. Mia"),
            ("SEAT-UDC-SAVAR-01", "UDC-SAVAR", "UDC Entrepreneur — Savar", RoleLevel.FIELD_WORKER, "SEAT-DC-DHAKA-ARB", "EMP-UDC-SAV", "T. Begum"),
        ]
        seats = {}
        for seat_id, off_code, desig, role, parent_id, emp_id, emp_name in seat_specs:
            obj, _ = DoptorSeat.objects.update_or_create(
                doptor_seat_id=seat_id,
                defaults={
                    "office": offices[off_code],
                    "designation_en": desig,
                    "role_level": role,
                    "parent_seat": seats.get(parent_id) if parent_id else None,
                    "incumbent_officer_id": emp_id,
                    "incumbent_name_en": emp_name,
                    "is_vacant": False,
                    "is_active": True,
                },
            )
            seats[seat_id] = obj
        return offices, seats

    def _seed_demo_accounts(self):
        account_specs = [
            ("citizen_demo", "Rafiqul", "Islam", "citizen.demo@mygov.bd", "+8801711100001", User.AccountType.CITIZEN, "", "", "", False, False, False),
            ("whistleblower_demo", "Protected", "Citizen", "whistleblower@mygov.bd", "+8801711100002", User.AccountType.CITIZEN, "", "", "", False, False, False),
            ("udc_operator", "Taslima", "Begum", "udc.savar@a2i.gov.bd", "+8801711100003", User.AccountType.OFFICER, "EMP-UDC-SAV", "SEAT-UDC-SAVAR-01", RoleLevel.FIELD_WORKER, False, False, False),
            ("gro_dncc", "Sabina", "Akter", "gro.z2@dncc.gov.bd", "+8801711100004", User.AccountType.OFFICER, "EMP-DNCC-Z2", "SEAT-DNCC-Z2-GRO", RoleLevel.GRO, False, False, False),
            ("supervisor_dpdc", "Engr. Reazul", "Islam", "exec.mirpur@dpdc.org.bd", "+8801711100005", User.AccountType.OFFICER, "EMP-DPDC-SUP", "SEAT-DPDC-MIRPUR-SUP", RoleLevel.SUPERVISOR, False, False, False),
            ("field_worker_1", "Kamal", "Mia", "fw.mirpur@dpdc.org.bd", "+8801711100006", User.AccountType.OFFICER, "EMP-DPDC-FW1", "SEAT-DPDC-MIRPUR-FW", RoleLevel.FIELD_WORKER, False, False, False),
            ("dc_dhaka_arbitrator", "Mahmudul", "Hossain", "dc.dhaka@mopa.gov.bd", "+8801711100007", User.AccountType.ARBITRATOR, "EMP-DC-DHK", "SEAT-DC-DHAKA-ARB", RoleLevel.APPELLATE, True, True, False),
            ("command_admin", "Dr. Abdus", "Salam", "command@cabinet.gov.bd", "+8801711100008", User.AccountType.ARBITRATOR, "EMP-CAB-001", "SEAT-CABINET-CMD-01", RoleLevel.APPELLATE, True, True, True),
        ]

        users = {}
        profiles = {}
        for uname, fn, ln, email, phone, atype, emp_id, seat_id, rlevel, oversight, staff, superu in account_specs:
            user, _ = User.objects.update_or_create(
                username=uname,
                defaults={
                    "first_name": fn,
                    "last_name": ln,
                    "email": email,
                    "phone_number": phone,
                    "account_type": atype,
                    "doptor_officer_id": emp_id,
                    "doptor_seat_id": seat_id,
                    "doptor_role_level": rlevel,
                    "is_oversight_cell": oversight,
                    "is_staff": staff,
                    "is_superuser": superu,
                    "is_active": True,
                },
            )
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
            users[uname] = user

            if atype == User.AccountType.CITIZEN:
                uct = CitizenIdentityService.compute_uct(f"demo-{uname}")
                pub_hash = CitizenIdentityService.compute_pseudonymous_hash(uct)
                prof, _ = CitizenProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "unified_citizen_token": uct,
                        "pseudonymous_public_hash": pub_hash,
                        "identity_provider": CitizenProfile.IdentityProvider.MYGOV_OIDC,
                        "identity_verified": True,
                        "verified_at": timezone.now(),
                        "nid_last4": phone[-4:],
                        "saved_address_en": "Section 10, Mirpur, Dhaka-1216",
                        "saved_address_bn": "সেকশন ১০, মিরপুর, ঢাকা-১২১৬",
                        "saved_bbs_geo_code": "302648",
                        "utility_accounts": {"dpdc_account": "DPDC-MRP-8821", "dwasa_account": "DWASA-Z04-912"},
                    },
                )
                profiles[uname] = prof
        return users, profiles

    def _log_once(self, complaint: Complaint, action: str, actor_id: str, seat_id: str = "", payload: dict | None = None):
        if not AuditLog.objects.filter(complaint=complaint, action=action).exists():
            AuditLog.objects.create(
                complaint=complaint,
                actor_id=actor_id,
                actor_seat_id=seat_id,
                actor_role="SYSTEM",
                action=action,
                entity_type="Complaint",
                entity_id=str(complaint.complaint_id),
                payload=payload or {"tracking_code": complaint.tracking_code},
            )

    def _seed_compound_mirpur_case(self, profile: CitizenProfile) -> int:
        now = timezone.now()
        pt = Point(90.3687, 23.8069, srid=4326)
        parent, created = Complaint.objects.get_or_create(
            tracking_code="BD-2026-DHK-9000100",
            defaults={
                "citizen_uct_hash": profile.pseudonymous_public_hash,
                "raw_text_bn": "মিরপুর ১০ নম্বরে ওয়াসার পানির মেইন পাইপ ফেটে গেছে, DPDC বিদ্যুতের খুঁটি হেলে পড়েছে এবং রাস্তা ভেঙে গেছে।",
                "raw_text_en": "Burst Dhaka WASA water main, snapped DPDC electric pole, and caved-in DNCC road in Mirpur-10.",
                "ai_category_code": "COMPOUND.MULTI_AGENCY",
                "ai_confidence": 0.94,
                "urgency_tier": Complaint.UrgencyTier.P1,
                "geo_point": pt,
                "admin_geo_code": "302648",
                "h3_hex_index": latlng_to_h3_res8(23.8069, 90.3687),
                "status": Complaint.ComplaintStatus.ROUTED,
                "sla_deadline_at": now + timedelta(hours=4),
            },
        )
        count = 1 if created else 0
        self._log_once(parent, "DEMO_COMPOUND_PARENT_CREATED", "SYSTEM-SEEDER")

        child_specs = [
            ("BD-2026-DHK-9000101", "POWER.SNAPPED_POLE_OUTAGE", Complaint.UrgencyTier.P1, Complaint.ComplaintStatus.IN_PROGRESS, "DOPTOR-OFF-DPDC-MRP", "SEAT-DPDC-MIRPUR-SUP", RoleLevel.SUPERVISOR, "Phase 1: De-energize and stabilize snapped DPDC pole."),
            ("BD-2026-DHK-9000102", "WATER.BURST_PIPE_SUPPLY", Complaint.UrgencyTier.P2, Complaint.ComplaintStatus.SUBMITTED, "DOPTOR-OFF-DWASA-004", "SEAT-DWASA-GRO-04", RoleLevel.GRO, "Phase 2: Repair burst Dhaka WASA 12-inch water main."),
            ("BD-2026-DHK-9000103", "URBAN_INFRA.ROAD_DRAINAGE_LIGHT", Complaint.UrgencyTier.P3, Complaint.ComplaintStatus.SUBMITTED, "DOPTOR-OFF-DNCC-Z2", "SEAT-DNCC-Z2-GRO", RoleLevel.GRO, "Phase 3: Resurface DNCC Mirpur-10 carriageway after utility work."),
        ]
        children = []
        for code, cat, tier, st, off_id, seat_id, role, desc in child_specs:
            c, c_new = Complaint.objects.get_or_create(
                tracking_code=code,
                defaults={
                    "parent_case": parent,
                    "citizen_uct_hash": profile.pseudonymous_public_hash,
                    "raw_text_en": desc,
                    "ai_category_code": cat,
                    "ai_confidence": 0.93,
                    "urgency_tier": tier,
                    "geo_point": pt,
                    "admin_geo_code": "302648",
                    "status": st,
                    "sla_deadline_at": now + timedelta(hours=48),
                },
            )
            if c_new:
                count += 1
            children.append(c)
            TicketAssignment.objects.get_or_create(
                complaint=c,
                role_level=role,
                is_active=True,
                defaults={
                    "doptor_office_id": off_id,
                    "doptor_seat_id": seat_id,
                    "due_at": now + timedelta(hours=24),
                },
            )
            WorkflowTracker.objects.get_or_create(
                complaint=c, defaults={"sla_started_at": now - timedelta(hours=1), "sla_total_seconds": 48 * 3600}
            )
            self._log_once(c, "DEMO_COMPOUND_CHILD_CREATED", "SYSTEM-SEEDER", seat_id)

        SubTicketDependency.objects.get_or_create(
            prerequisite_ticket=children[0],
            dependent_ticket=children[1],
            defaults={"parent_case": parent, "sequence_order": 1, "reason": "DPDC power safety must finish before WASA excavation."},
        )
        SubTicketDependency.objects.get_or_create(
            prerequisite_ticket=children[1],
            dependent_ticket=children[2],
            defaults={"parent_case": parent, "sequence_order": 2, "reason": "WASA pipe repair must finish before DNCC road resurfacing."},
        )
        return count

    def _seed_200m_hotspot_cluster_mirpur(self, profile: CitizenProfile) -> int:
        now = timezone.now()
        master_pt = Point(90.3654, 23.8042, srid=4326)
        master, m_new = Complaint.objects.get_or_create(
            tracking_code="BD-2026-DHK-9000200",
            defaults={
                "citizen_uct_hash": profile.pseudonymous_public_hash,
                "raw_text_bn": "মিরপুর ১২ ট্রান্সফরমার বিস্ফোরণ হয়ে পুরো ব্লকে বিদ্যুৎ বিচ্ছিন্ন।",
                "raw_text_en": "Mirpur-12 11kV transformer explosion — entire block without electricity (12 resident reports clustered).",
                "ai_category_code": "POWER.FEEDER_FAULT",
                "ai_confidence": 0.96,
                "urgency_tier": Complaint.UrgencyTier.P1,
                "geo_point": master_pt,
                "admin_geo_code": "302648",
                "h3_hex_index": latlng_to_h3_res8(23.8042, 90.3654),
                "status": Complaint.ComplaintStatus.IN_PROGRESS,
                "sla_deadline_at": now + timedelta(hours=4),
            },
        )
        count = 1 if m_new else 0
        TicketAssignment.objects.get_or_create(
            complaint=master,
            role_level=RoleLevel.SUPERVISOR,
            is_active=True,
            defaults={
                "doptor_office_id": "DOPTOR-OFF-DPDC-MRP",
                "doptor_seat_id": "SEAT-DPDC-MIRPUR-SUP",
                "assigned_officer_id": "EMP-DPDC-SUP",
                "due_at": now + timedelta(hours=3),
            },
        )
        WorkflowTracker.objects.get_or_create(
            complaint=master, defaults={"sla_started_at": now - timedelta(minutes=45), "sla_total_seconds": 4 * 3600}
        )
        MasterIncidentSubscription.objects.get_or_create(
            master_complaint=master, citizen_uct_hash=profile.pseudonymous_public_hash
        )
        self._log_once(master, "DEMO_MASTER_INCIDENT_CLUSTER_BOOSTED_P1", "SYSTEM-SPATIAL-DEDUP", "SEAT-DPDC-MIRPUR-SUP")

        # 11 nearby resident duplicates within 200m (total 12 linked complaints)
        for i in range(1, 12):
            res_hash = hashlib.sha256(f"mirpur-resident-{i}".encode("utf-8")).hexdigest()
            dup, d_new = Complaint.objects.get_or_create(
                tracking_code=f"BD-2026-DHK-90002{i:02d}",
                defaults={
                    "master_cluster": master,
                    "citizen_uct_hash": res_hash,
                    "raw_text_en": f"Mirpur-12 transformer blast outage report #{i + 1} (within 200m).",
                    "ai_category_code": "POWER.FEEDER_FAULT",
                    "ai_confidence": 0.92,
                    "urgency_tier": Complaint.UrgencyTier.P2,
                    "geo_point": Point(90.3654 + (i * 0.00008), 23.8042 + (i * 0.00005), srid=4326),
                    "admin_geo_code": "302648",
                    "status": Complaint.ComplaintStatus.MERGED_DUPLICATE,
                },
            )
            if d_new:
                count += 1
            MasterIncidentSubscription.objects.get_or_create(
                master_complaint=master,
                citizen_uct_hash=res_hash,
                defaults={"duplicate_complaint": dup},
            )
        return count

    def _seed_two_key_verification_cases(self, profile: CitizenProfile) -> int:
        now = timezone.now()
        specs = [
            ("BD-2026-DHK-9000301", "Streetlight and drainage silt cleared on Mirpur Road 7.", 90.3691, 23.8075, 12.4),
            ("BD-2026-DHK-9000302", "Broken manhole cover replaced near Pallabi bus stand.", 90.3640, 23.8211, 28.7),
        ]
        count = 0
        for code, summary, lon, lat, dist_m in specs:
            c, c_new = Complaint.objects.get_or_create(
                tracking_code=code,
                defaults={
                    "citizen_uct_hash": profile.pseudonymous_public_hash,
                    "raw_text_en": summary,
                    "ai_category_code": "URBAN_INFRA.ROAD_DRAINAGE_LIGHT",
                    "ai_confidence": 0.91,
                    "urgency_tier": Complaint.UrgencyTier.P3,
                    "geo_point": Point(lon, lat, srid=4326),
                    "admin_geo_code": "302648",
                    "status": Complaint.ComplaintStatus.PENDING_CITIZEN_VERIFY,
                    "sla_deadline_at": now + timedelta(days=5),
                },
            )
            if c_new:
                count += 1
            WorkflowTracker.objects.update_or_create(
                complaint=c,
                defaults={
                    "sla_started_at": now - timedelta(days=2),
                    "sla_total_seconds": 10 * 86400,
                    "pending_citizen_verify_at": now - timedelta(hours=2),
                    "citizen_verify_deadline_at": now + timedelta(hours=70),
                },
            )
            ResolutionReport.objects.get_or_create(
                complaint=c,
                submitted_by_seat="SEAT-DPDC-MIRPUR-FW",
                defaults={
                    "work_summary": f"Field team verified and completed: {summary}",
                    "after_photo_urls": ["https://minio.local/grievance-media-encrypted/resolutions/demo-after.jpg"],
                    "gps_verified_dist_m": dist_m,
                    "citizen_verdict": ResolutionReport.CitizenVerdict.PENDING,
                },
            )
            self._log_once(c, "DEMO_TWO_KEY_PENDING_CITIZEN_VERIFY", "EMP-DPDC-SUP", "SEAT-DPDC-MIRPUR-SUP")
        return count

    def _seed_governance_safeguard_cases(self, profile: CitizenProfile) -> int:
        now = timezone.now()
        count = 0

        # 1. ARBITRATION_LOCKED (transfer_count=2, WASA vs DNCC)
        arb_c, c1 = Complaint.objects.get_or_create(
            tracking_code="BD-2026-DHK-9000401",
            defaults={
                "citizen_uct_hash": profile.pseudonymous_public_hash,
                "raw_text_en": "Stormwater box-culvert overflow disputed between Dhaka WASA and DNCC Zone-2.",
                "ai_category_code": "WATER.BURST_PIPE_SUPPLY",
                "ai_confidence": 0.74,
                "urgency_tier": Complaint.UrgencyTier.P2,
                "geo_point": Point(90.3712, 23.8091, srid=4326),
                "admin_geo_code": "302648",
                "status": Complaint.ComplaintStatus.ARBITRATION_LOCKED,
                "transfer_count": 2,
                "is_arbitration_locked": True,
                "sla_deadline_at": now + timedelta(hours=36),
            },
        )
        if c1:
            count += 1
        ArbitrationCase.objects.get_or_create(
            complaint=arb_c,
            defaults={
                "jurisdiction_scope": ArbitrationCase.JurisdictionScope.DISTRICT_DC,
                "arbitrator_seat_id": "SEAT-DC-DHAKA-ARB",
                "decision_sla_deadline_at": now + timedelta(hours=20),
                "disputing_seats": ["SEAT-DNCC-Z2-GRO", "SEAT-DWASA-GRO-04"],
            },
        )
        TriageRun.objects.get_or_create(
            complaint=arb_c,
            routing_decision=TriageRun.RoutingDecision.GRO_REASSIGN_FLAGGED,
            defaults={
                "primary_ministry_code": "MIN-LGRD",
                "primary_agency_code": "DWASA",
                "confidence_score": 0.74,
                "gro_one_click_reassign_flag": True,
            },
        )
        self._log_once(arb_c, "DEMO_ARBITRATION_LOCKED_2_TRANSFERS", "SYSTEM-WORKFLOW", "SEAT-DC-DHAKA-ARB")

        # 2. ON_HOLD_PROCUREMENT with e-GP Tender ID + 4 Capital Milestones
        egp_c, c2 = Complaint.objects.get_or_create(
            tracking_code="BD-2026-DHK-9000402",
            defaults={
                "citizen_uct_hash": profile.pseudonymous_public_hash,
                "raw_text_en": "Full reconstruction of 1.2km Mirpur-2 feeder road requiring e-GP capital tender.",
                "ai_category_code": "URBAN_INFRA.ROAD_DRAINAGE_LIGHT",
                "ai_confidence": 0.91,
                "urgency_tier": Complaint.UrgencyTier.P4,
                "geo_point": Point(90.3610, 23.8040, srid=4326),
                "admin_geo_code": "302648",
                "status": Complaint.ComplaintStatus.ON_HOLD_PROCUREMENT,
                "hold_reason_code": Complaint.HoldReasonCode.EGP_TENDER,
                "hold_reference_id": "EGP-2026-441092",
                "sla_deadline_at": now + timedelta(days=30),
            },
        )
        if c2:
            count += 1
        WorkflowTracker.objects.update_or_create(
            complaint=egp_c,
            defaults={"sla_started_at": now - timedelta(days=4), "sla_total_seconds": 30 * 86400, "sla_paused_at": now - timedelta(days=2)},
        )
        for stg, order, done in (
            (CapitalMilestone.Stage.BUDGET_APPROVED, 1, True),
            (CapitalMilestone.Stage.EGP_TENDER_FLOATED, 2, True),
            (CapitalMilestone.Stage.WORK_ORDER_ISSUED, 3, False),
            (CapitalMilestone.Stage.EXECUTION, 4, False),
        ):
            CapitalMilestone.objects.update_or_create(
                complaint=egp_c,
                stage=stg,
                defaults={
                    "stage_order": order,
                    "reference_type": CapitalMilestone.ReferenceType.EGP_TENDER,
                    "reference_id": "EGP-2026-441092",
                    "is_completed": done,
                    "completed_at": now - timedelta(days=1) if done else None,
                    "updated_by_seat": "SEAT-DNCC-Z2-GRO",
                },
            )
        self._log_once(egp_c, "DEMO_ON_HOLD_PROCUREMENT_EGP", "EMP-DNCC-Z2", "SEAT-DNCC-Z2-GRO")

        # 3. CONTESTED_BY_OFFICER (48h Right of Reply)
        con_c, c3 = Complaint.objects.get_or_create(
            tracking_code="BD-2026-DHK-9000403",
            defaults={
                "citizen_uct_hash": profile.pseudonymous_public_hash,
                "raw_text_en": "Citizen contested streetlight repair timing; GRO uploaded 48h counter-evidence.",
                "ai_category_code": "URBAN_INFRA.ROAD_DRAINAGE_LIGHT",
                "ai_confidence": 0.89,
                "urgency_tier": Complaint.UrgencyTier.P3,
                "geo_point": Point(90.3700, 23.8050, srid=4326),
                "admin_geo_code": "302648",
                "status": Complaint.ComplaintStatus.CONTESTED_BY_OFFICER,
                "officer_rebuttal_url": "https://minio.local/grievance-media-encrypted/rebuttals/dncc-log-403.pdf",
                "sla_deadline_at": now + timedelta(days=3),
            },
        )
        if c3:
            count += 1
        WorkflowTracker.objects.update_or_create(
            complaint=con_c,
            defaults={
                "sla_started_at": now - timedelta(days=5),
                "sla_total_seconds": 10 * 86400,
                "officer_rebuttal_deadline_at": now + timedelta(hours=44),
            },
        )
        TicketAssignment.objects.get_or_create(
            complaint=con_c,
            role_level=RoleLevel.GRO,
            is_active=True,
            defaults={"doptor_office_id": "DOPTOR-OFF-DNCC-Z2", "doptor_seat_id": "SEAT-DNCC-Z2-GRO", "due_at": now + timedelta(hours=18)},
        )
        self._log_once(con_c, "DEMO_CONTESTED_BY_OFFICER_48H", "EMP-DNCC-Z2", "SEAT-DNCC-Z2-GRO")

        # 4. UNFOUNDED_CLEARED with citizen strike tracking + Tier-3 DDCC item on an escalated case
        unf_c, c4 = Complaint.objects.get_or_create(
            tracking_code="BD-2026-DHK-9000404",
            defaults={
                "citizen_uct_hash": profile.pseudonymous_public_hash,
                "raw_text_en": "Verified unfounded report (site inspection proved no illegal encroachment existed).",
                "ai_category_code": "LAND.MUTATION_KHATIAN",
                "ai_confidence": 0.88,
                "urgency_tier": Complaint.UrgencyTier.P3,
                "geo_point": Point(90.3660, 23.8010, srid=4326),
                "admin_geo_code": "302648",
                "status": Complaint.ComplaintStatus.UNFOUNDED_CLEARED,
            },
        )
        if c4:
            count += 1
            if profile.strike_count == 0:
                profile.record_verified_false_filing("Demo verified unfounded filing on BD-2026-DHK-9000404.")
        self._log_once(unf_c, "DEMO_UNFOUNDED_CLEARED_ZERO_PENALTY", "EMP-DC-DHK", "SEAT-DC-DHAKA-ARB")

        # Seed 1 DDCC Level-3 Escalation Event so Command Center DDCC table is immediately populated
        ev, _ = EscalationEvent.objects.get_or_create(
            complaint=arb_c,
            event_type=EscalationEvent.EventType.SLA_BREACH_100,
            escalation_tier=3,
            defaults={
                "from_seat_id": "SEAT-DNCC-Z2-GRO",
                "to_seat_id": "SEAT-DC-DHAKA-ARB",
                "apa_scorecard_impact": -5.0,
                "ddcc_flagged": True,
                "notes": "Demo Tier-3 escalation surfaced to Monthly Dhaka DDCC Agenda.",
            },
        )
        DDCCAgendaItem.objects.get_or_create(
            complaint=arb_c,
            agenda_month=now.strftime("%Y-%m"),
            defaults={
                "escalation_event": ev,
                "district_bbs_code": "3026",
                "summary": "Tier-3 inter-agency drainage dispute (WASA vs DNCC Zone-2) scheduled for Monthly DDCC.",
            },
        )
        return count

    def _seed_whistleblower_vault_case(self, wb_profile: CitizenProfile) -> int:
        c, created = Complaint.objects.get_or_create(
            tracking_code="BD-2026-DHK-9000501",
            defaults={
                "citizen_uct_hash": wb_profile.pseudonymous_public_hash,
                "is_anonymous": True,
                "raw_text_bn": "স্থানীয় দপ্তরে অবৈধ ঘুষ দাবির গোপন অভিযোগ।",
                "raw_text_en": "Confidential whistleblower report of irregular facilitation fees at local office.",
                "ai_category_code": "LAND.MUTATION_KHATIAN",
                "ai_confidence": 0.90,
                "urgency_tier": Complaint.UrgencyTier.P2,
                "geo_point": Point(90.4125, 23.7900, srid=4326),
                "admin_geo_code": "30262619",
                "status": Complaint.ComplaintStatus.ROUTED,
            },
        )
        WhistleblowerPrivacyService().seal_identity(
            complaint_id=c.complaint_id, citizen_profile=wb_profile
        )
        self._log_once(c, "DEMO_WHISTLEBLOWER_VAULT_SEALED", "SYSTEM-VAULT")
        return 1 if created else 0

    def _seed_disaster_surge_sylhet_feni(self, profile: CitizenProfile) -> int:
        now = timezone.now()
        sylhet_geom = _box(91.70, 24.80, 92.05, 25.05)
        crisis, _ = CrisisZone.objects.update_or_create(
            crisis_code="FLOOD-SYLHET-FENI-2026",
            defaults={
                "name_en": "Sylhet & Feni Flash Flood Emergency Zone",
                "name_bn": "সিলেট ও ফেনী আকস্মিক বন্যা জরুরি এলাকা",
                "disaster_type": CrisisZone.DisasterType.FLASH_FLOOD,
                "trigger_source": CrisisZone.TriggerSource.MODMR_TOGGLE,
                "geom": sylhet_geom,
                "baseline_rate_per_hour": 12.0,
                "peak_rate_per_hour": 84.0,
                "frozen_ticket_count": 2,
                "is_active": True,
                "activated_by_seat": "SEAT-CABINET-CMD-01",
            },
        )

        count = 0
        # 2 P1 Life-Safety Fast-Lane Rescue tickets + H3 Res-8 heatmap cells
        rescue_specs = [
            ("BD-2026-SYL-9000601", 24.8949, 91.8687, "Family of 5 trapped on roof in Sylhet floodwater, medical emergency!"),
            ("BD-2026-CTG-9000602", 23.0159, 91.3976, "Feni embankment breach with live wire in water near shelter!"),
        ]
        for code, lat, lon, msg in rescue_specs:
            c, c_new = Complaint.objects.get_or_create(
                tracking_code=code,
                defaults={
                    "citizen_uct_hash": profile.pseudonymous_public_hash,
                    "raw_text_en": msg,
                    "ai_category_code": "DISASTER.LIFE_SAFETY_RESCUE",
                    "ai_confidence": 0.97,
                    "urgency_tier": Complaint.UrgencyTier.P1,
                    "geo_point": Point(lon, lat, srid=4326),
                    "admin_geo_code": "6091",
                    "h3_hex_index": latlng_to_h3_res8(lat, lon),
                    "crisis_zone_id": crisis.crisis_id,
                    "status": Complaint.ComplaintStatus.IN_PROGRESS,
                    "sla_deadline_at": now + timedelta(hours=4),
                },
            )
            if c_new:
                count += 1
            if not EmergencyCommandDispatch.objects.filter(complaint=c).exists():
                H3SurgeIngestionService.ingest_surge_report(
                    lat=lat,
                    lon=lon,
                    message=msg,
                    citizen_phone="+8801711100001",
                    crisis_zone=crisis,
                    complaint=c,
                )
            self._log_once(c, "DEMO_DISASTER_P1_FASTLANE_DISPATCHED", "SYSTEM-DISASTER")

        # 2 Routine P3/P4 tickets frozen in DISASTER_SLA_SUSPENDED
        frozen_specs = [
            ("BD-2026-SYL-9000603", Complaint.UrgencyTier.P3, "Routine park bench repair in Sylhet Ward 4 (SLA frozen during flood)."),
            ("BD-2026-SYL-9000604", Complaint.UrgencyTier.P4, "Long-term drainage beautification request (SLA frozen during flood)."),
        ]
        for code, tier, msg in frozen_specs:
            c, c_new = Complaint.objects.get_or_create(
                tracking_code=code,
                defaults={
                    "citizen_uct_hash": profile.pseudonymous_public_hash,
                    "raw_text_en": msg,
                    "ai_category_code": "URBAN_INFRA.ROAD_DRAINAGE_LIGHT",
                    "ai_confidence": 0.86,
                    "urgency_tier": tier,
                    "geo_point": Point(91.8710, 24.8990, srid=4326),
                    "admin_geo_code": "6091",
                    "crisis_zone_id": crisis.crisis_id,
                    "hold_reason_code": Complaint.HoldReasonCode.DISASTER_FREEZE,
                    "hold_reference_id": crisis.crisis_code,
                    "status": Complaint.ComplaintStatus.DISASTER_SLA_SUSPENDED,
                },
            )
            if c_new:
                count += 1
            self._log_once(c, "DEMO_DISASTER_ROUTINE_SLA_SUSPENDED", "SYSTEM-CIRCUIT-BREAKER")
        return count
