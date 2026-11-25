from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from apps.accounts.models import User
from apps.accounts.permissions import IsAssignedSeatOrSupervisor
from apps.complaints.models import AuditLog, Complaint
from apps.organogram.models import DoptorOffice, DoptorSeat, DoptorVacancyAlert, RoleLevel
from apps.organogram.services.doptor_sso import DoptorSSOService
from apps.organogram.services.seat_router import ZeroBlackHoleSeatRouter


@override_settings(DOPTOR_PROVIDER_MODE="mock")
class DoptorSSOAndSeatRouterTests(TestCase):
    def setUp(self):
        self.office = DoptorOffice.objects.create(
            doptor_office_id="DOPTOR-OFF-DNCC-TEST",
            office_code="DNCC-TEST",
            name_en="Dhaka North City Corporation (Test)",
            office_layer=DoptorOffice.OfficeLayer.CITY_CORP,
            bbs_geo_code="3026",
        )
        self.supervisor_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-DNCC-APP-TEST",
            office=self.office,
            designation_en="Appellate CEO",
            role_level=RoleLevel.APPELLATE,
            incumbent_officer_id="OFF-APP-01",
            incumbent_name_en="Dr. Appellate",
            is_vacant=False,
        )
        self.addl_charge_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-DNCC-GRO-ADDL",
            office=self.office,
            designation_en="Zonal Officer Zone 2 (Additional Charge)",
            role_level=RoleLevel.GRO,
            parent_seat=self.supervisor_seat,
            incumbent_officer_id="OFF-ADDL-02",
            incumbent_name_en="M. Additional",
            is_vacant=False,
        )
        self.primary_seat = DoptorSeat.objects.create(
            doptor_seat_id="SEAT-DNCC-GRO-PRIMARY",
            office=self.office,
            designation_en="Zonal Officer Zone 3 (Primary GRO)",
            role_level=RoleLevel.GRO,
            parent_seat=self.supervisor_seat,
            additional_charge_seat=self.addl_charge_seat,
            doptor_hr_email="hr.dncc@doptor.gov.bd",
            incumbent_officer_id="OFF-PRI-03",
            incumbent_name_en="N. Primary",
            is_vacant=False,
        )
        self.complaint = Complaint.objects.create(
            citizen_uct_hash="a" * 64,
            raw_text_en="Broken drainage culvert on Road 11.",
            admin_geo_code="30262619",
        )

    def test_doptor_sso_syncs_full_ministry_to_seat_hierarchy(self):
        result = DoptorSSOService().authenticate_and_sync("mock-doptor-token-102938")
        self.assertEqual(
            result.synced_hierarchy_codes,
            ["MIN-LGRD", "DIR-LGED", "DIV-DHK", "DIST-DHK", "UPZ-SAVAR-LGED"],
        )
        self.assertEqual(result.user.doptor_seat_id, "SEAT-LGED-SAVAR-GRO-01")
        self.assertEqual(result.seat.office.office_code, "UPZ-SAVAR-LGED")
        self.assertEqual(result.seat.office.parent_office.office_code, "DIST-DHK")

    def test_zero_black_hole_tier1_occupied_primary_seat(self):
        router = ZeroBlackHoleSeatRouter()
        assignment, res = router.assign_complaint_to_seat(
            complaint=self.complaint,
            target_seat_id=self.primary_seat.doptor_seat_id,
            fire_hr_alert=False,
        )
        self.assertEqual(res.fallback_tier, "PRIMARY_OCCUPIED")
        self.assertEqual(assignment.doptor_seat_id, self.primary_seat.doptor_seat_id)
        self.assertEqual(DoptorVacancyAlert.objects.count(), 0)

    def test_zero_black_hole_tier2_vacant_routes_to_additional_charge_seat(self):
        self.primary_seat.is_vacant = True
        self.primary_seat.incumbent_officer_id = ""
        self.primary_seat.save()

        router = ZeroBlackHoleSeatRouter()
        assignment, res = router.assign_complaint_to_seat(
            complaint=self.complaint,
            target_seat_id=self.primary_seat.doptor_seat_id,
            fire_hr_alert=False,
        )
        self.assertEqual(res.fallback_tier, DoptorVacancyAlert.FallbackTier.ADDITIONAL_CHARGE)
        self.assertEqual(assignment.doptor_seat_id, self.addl_charge_seat.doptor_seat_id)
        self.assertEqual(DoptorVacancyAlert.objects.count(), 0)

    def test_zero_black_hole_tier3_vacant_no_addl_routes_to_supervisor_and_fires_hr_alert(self):
        self.primary_seat.is_vacant = True
        self.primary_seat.incumbent_officer_id = ""
        self.primary_seat.additional_charge_seat = None
        self.primary_seat.save()

        router = ZeroBlackHoleSeatRouter()
        assignment, res = router.assign_complaint_to_seat(
            complaint=self.complaint,
            target_seat_id=self.primary_seat.doptor_seat_id,
            fire_hr_alert=False,
        )
        self.assertEqual(res.fallback_tier, DoptorVacancyAlert.FallbackTier.IMMEDIATE_SUPERVISOR)
        self.assertEqual(assignment.doptor_seat_id, self.supervisor_seat.doptor_seat_id)
        self.assertIsNotNone(res.vacancy_alert)
        self.assertEqual(DoptorVacancyAlert.objects.count(), 1)
        self.assertTrue(
            AuditLog.objects.filter(
                complaint=self.complaint, action="VACANT_SEAT_SUPERVISOR_FALLBACK"
            ).exists()
        )
        is_valid, _checked, broken = AuditLog.verify_chain()
        self.assertTrue(is_valid)
        self.assertIsNone(broken)

    def test_object_rbac_allows_assigned_seat_and_supervisor_denies_unrelated_seat(self):
        ZeroBlackHoleSeatRouter().assign_complaint_to_seat(
            complaint=self.complaint,
            target_seat_id=self.primary_seat.doptor_seat_id,
            fire_hr_alert=False,
        )
        factory = APIRequestFactory()
        perm = IsAssignedSeatOrSupervisor()

        assigned_user = User.objects.create_user(
            username="pri_officer",
            account_type=User.AccountType.OFFICER,
            doptor_seat_id=self.primary_seat.doptor_seat_id,
            doptor_role_level=RoleLevel.GRO,
        )
        sup_user = User.objects.create_user(
            username="sup_officer",
            account_type=User.AccountType.OFFICER,
            doptor_seat_id=self.supervisor_seat.doptor_seat_id,
            doptor_role_level=RoleLevel.APPELLATE,
        )
        other_user = User.objects.create_user(
            username="other_officer",
            account_type=User.AccountType.OFFICER,
            doptor_seat_id="SEAT-UNRELATED-99",
            doptor_role_level=RoleLevel.GRO,
        )

        req = factory.get("/")
        req.user = assigned_user
        self.assertTrue(perm.has_object_permission(req, None, self.complaint))

        req.user = sup_user
        self.assertTrue(perm.has_object_permission(req, None, self.complaint))

        req.user = other_user
        self.assertFalse(perm.has_object_permission(req, None, self.complaint))
