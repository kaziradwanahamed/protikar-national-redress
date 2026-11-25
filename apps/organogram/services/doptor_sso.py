"""Government Official SSO (Doptor / Nothi) syncing full organogram hierarchy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.organogram.models import DoptorOffice, DoptorSeat, RoleLevel


class DoptorSSOError(ValueError):
    """Raised when Doptor SSO token exchange or organogram sync fails."""


@dataclass(frozen=True)
class DoptorAuthResult:
    user: User
    office: DoptorOffice
    seat: DoptorSeat
    synced_hierarchy_codes: list[str]


class DoptorSSOService:
    """
    Authenticates government officers via Doptor SSO and synchronizes:
    Ministry -> Directorate -> Division -> District -> Upazila -> Office -> Designation (doptor_seat_id).
    Tickets are bound strictly to `doptor_seat_id`, never permanently to individual user IDs.
    """

    def __init__(self, timeout_seconds: float = 10.0):
        self.timeout_seconds = timeout_seconds

    def fetch_doptor_claims(self, doptor_token: str) -> dict[str, Any]:
        if not doptor_token or doptor_token.startswith("invalid"):
            raise DoptorSSOError("Invalid or expired Doptor SSO token.")

        if getattr(settings, "DOPTOR_PROVIDER_MODE", "mock").lower() == "production":
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.get(
                    f"{settings.DOPTOR_ORGANOGRAM_API_URL.rstrip('/')}/me",
                    headers={"Authorization": f"Bearer {doptor_token}"},
                )
                if resp.status_code != 200:
                    raise DoptorSSOError(f"Doptor organogram API returned HTTP {resp.status_code}.")
                return resp.json()

        # Configurable mock Doptor SSO payload for local dev & automated testing
        return {
            "officer_id": f"DOPTOR-EMP-{doptor_token[-6:].upper()}",
            "username": f"doptor_{doptor_token[-6:].lower()}",
            "name_en": "Engr. Mahmudul Hasan",
            "name_bn": "প্রকৌশলী মাহমুদুল হাসান",
            "email": f"{doptor_token[-6:].lower()}@lged.gov.bd",
            "phone_number": "+8801712000444",
            "is_oversight_cell": "oversight" in doptor_token.lower(),
            "hierarchy": [
                {
                    "doptor_office_id": "DOPTOR-MIN-LGRD",
                    "office_code": "MIN-LGRD",
                    "name_en": "Ministry of Local Government, Rural Development and Co-operatives",
                    "name_bn": "স্থানীয় সরকার, পল্লী উন্নয়ন ও সমবায় মন্ত্রণালয়",
                    "office_layer": DoptorOffice.OfficeLayer.MINISTRY,
                    "ministry_code": "MIN-LGRD",
                    "bbs_geo_code": "",
                },
                {
                    "doptor_office_id": "DOPTOR-DIR-LGED",
                    "office_code": "DIR-LGED",
                    "name_en": "Local Government Engineering Department (LGED)",
                    "name_bn": "স্থানীয় সরকার প্রকৌশল অধিদপ্তর",
                    "office_layer": DoptorOffice.OfficeLayer.DIRECTORATE,
                    "ministry_code": "MIN-LGRD",
                    "directorate_code": "DIR-LGED",
                    "bbs_geo_code": "",
                },
                {
                    "doptor_office_id": "DOPTOR-DIV-30",
                    "office_code": "DIV-DHK",
                    "name_en": "Dhaka Division Office",
                    "name_bn": "ঢাকা বিভাগীয় কার্যালয়",
                    "office_layer": DoptorOffice.OfficeLayer.DIVISION,
                    "ministry_code": "MIN-LGRD",
                    "directorate_code": "DIR-LGED",
                    "division_code": "30",
                    "bbs_geo_code": "30",
                },
                {
                    "doptor_office_id": "DOPTOR-DIST-3026",
                    "office_code": "DIST-DHK",
                    "name_en": "Dhaka District Executive Engineer Office (LGED)",
                    "name_bn": "ঢাকা জেলা নির্বাহী প্রকৌশলীর কার্যালয়",
                    "office_layer": DoptorOffice.OfficeLayer.DISTRICT,
                    "ministry_code": "MIN-LGRD",
                    "directorate_code": "DIR-LGED",
                    "division_code": "30",
                    "district_code": "26",
                    "bbs_geo_code": "3026",
                },
                {
                    "doptor_office_id": "DOPTOR-UPZ-302672",
                    "office_code": "UPZ-SAVAR-LGED",
                    "name_en": "Savar Upazila Engineer Office (LGED)",
                    "name_bn": "সাভার উপজেলা প্রকৌশলীর কার্যালয়",
                    "office_layer": DoptorOffice.OfficeLayer.UPAZILA,
                    "ministry_code": "MIN-LGRD",
                    "directorate_code": "DIR-LGED",
                    "division_code": "30",
                    "district_code": "26",
                    "upazila_code": "72",
                    "bbs_geo_code": "302672",
                },
            ],
            "seat": {
                "doptor_seat_id": "SEAT-LGED-SAVAR-GRO-01",
                "designation_en": "Upazila Engineer — Savar (GRO)",
                "designation_bn": "উপজেলা প্রকৌশলী — সাভার (অভিযোগ নিষ্পত্তি কর্মকর্তা)",
                "role_level": RoleLevel.GRO,
                "doptor_hr_email": "hr.lged@doptor.gov.bd",
            },
        }

    @transaction.atomic
    def authenticate_and_sync(self, doptor_token: str) -> DoptorAuthResult:
        claims = self.fetch_doptor_claims(doptor_token)
        hierarchy = claims.get("hierarchy") or []
        if not hierarchy:
            raise DoptorSSOError("Doptor claims missing organogram hierarchy.")

        now = timezone.now()
        parent_office: DoptorOffice | None = None
        synced_codes: list[str] = []

        for node in hierarchy:
            office, _ = DoptorOffice.objects.update_or_create(
                doptor_office_id=node["doptor_office_id"],
                defaults={
                    "office_code": node["office_code"],
                    "name_en": node["name_en"],
                    "name_bn": node.get("name_bn", ""),
                    "office_layer": node["office_layer"],
                    "ministry_code": node.get("ministry_code", ""),
                    "directorate_code": node.get("directorate_code", ""),
                    "division_code": node.get("division_code", ""),
                    "district_code": node.get("district_code", ""),
                    "upazila_code": node.get("upazila_code", ""),
                    "bbs_geo_code": node.get("bbs_geo_code", ""),
                    "parent_office": parent_office,
                    "last_synced_at": now,
                    "is_active": True,
                },
            )
            parent_office = office
            synced_codes.append(office.office_code)

        leaf_office = parent_office
        seat_data = claims["seat"]
        seat, _ = DoptorSeat.objects.update_or_create(
            doptor_seat_id=seat_data["doptor_seat_id"],
            defaults={
                "office": leaf_office,
                "designation_en": seat_data["designation_en"],
                "designation_bn": seat_data.get("designation_bn", ""),
                "role_level": seat_data.get("role_level", RoleLevel.GRO),
                "doptor_hr_email": seat_data.get("doptor_hr_email", ""),
                "incumbent_officer_id": claims["officer_id"],
                "incumbent_name_en": claims.get("name_en", ""),
                "incumbent_name_bn": claims.get("name_bn", ""),
                "is_vacant": False,
                "is_active": True,
            },
        )

        first_name, _, last_name = claims.get("name_en", "").partition(" ")
        user, _ = User.objects.update_or_create(
            doptor_officer_id=claims["officer_id"],
            defaults={
                "username": claims.get("username") or f"off_{claims['officer_id'].lower()}",
                "first_name": first_name[:150],
                "last_name": last_name[:150],
                "email": claims.get("email", ""),
                "phone_number": claims.get("phone_number", ""),
                "account_type": User.AccountType.OFFICER,
                "doptor_seat_id": seat.doptor_seat_id,
                "doptor_role_level": seat.role_level,
                "is_oversight_cell": bool(claims.get("is_oversight_cell", False)),
                "is_active": True,
            },
        )
        return DoptorAuthResult(
            user=user,
            office=leaf_office,
            seat=seat,
            synced_hierarchy_codes=synced_codes,
        )
