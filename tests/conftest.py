"""Shared pytest fixtures for end-to-end Bangladesh Grievance Platform integration tests."""

import pytest
from django.contrib.gis.geos import MultiPolygon, Point, Polygon

from apps.accounts.models import User
from apps.accounts.services.oidc_providers import CitizenIdentityService, get_identity_provider
from apps.organogram.models import DoptorOffice, DoptorSeat, RoleLevel, ServiceAreaPolygon


@pytest.fixture
def ndc_org_fixture(db):
    """Creates a realistic DNCC + WASA Doptor seat hierarchy and Gulshan PostGIS polygon."""
    dncc = DoptorOffice.objects.create(
        doptor_office_id="E2E-OFF-DNCC",
        office_code="E2E-DNCC",
        name_en="Dhaka North City Corporation",
        office_layer=DoptorOffice.OfficeLayer.CITY_CORP,
        ministry_code="MIN-LGRD",
        district_code="26",
        upazila_code="26",
        bbs_geo_code="302626",
    )
    wasa = DoptorOffice.objects.create(
        doptor_office_id="E2E-OFF-WASA",
        office_code="E2E-WASA",
        name_en="Dhaka WASA",
        office_layer=DoptorOffice.OfficeLayer.UTILITY,
        ministry_code="MIN-LGRD",
        district_code="26",
        upazila_code="48",
        bbs_geo_code="302648",
    )

    appellate = DoptorSeat.objects.create(
        doptor_seat_id="E2E-SEAT-APP",
        office=dncc,
        designation_en="CEO DNCC (Appellate)",
        role_level=RoleLevel.APPELLATE,
        incumbent_officer_id="E2E-EMP-APP",
    )
    addl_gro = DoptorSeat.objects.create(
        doptor_seat_id="E2E-SEAT-GRO-ADDL",
        office=dncc,
        designation_en="Additional Charge GRO",
        role_level=RoleLevel.GRO,
        parent_seat=appellate,
        incumbent_officer_id="E2E-EMP-ADDL",
    )
    gro = DoptorSeat.objects.create(
        doptor_seat_id="E2E-SEAT-GRO",
        office=dncc,
        designation_en="Zonal GRO Ward 19",
        role_level=RoleLevel.GRO,
        parent_seat=appellate,
        additional_charge_seat=addl_gro,
        doptor_hr_email="hr.dncc@doptor.gov.bd",
        incumbent_officer_id="E2E-EMP-GRO",
    )
    sup = DoptorSeat.objects.create(
        doptor_seat_id="E2E-SEAT-SUP",
        office=dncc,
        designation_en="Assistant Engineer",
        role_level=RoleLevel.SUPERVISOR,
        parent_seat=gro,
        incumbent_officer_id="E2E-EMP-SUP",
    )
    fw = DoptorSeat.objects.create(
        doptor_seat_id="E2E-SEAT-FW",
        office=dncc,
        designation_en="Sub-Assistant Engineer",
        role_level=RoleLevel.FIELD_WORKER,
        parent_seat=sup,
        incumbent_officer_id="E2E-EMP-FW",
    )
    wasa_gro = DoptorSeat.objects.create(
        doptor_seat_id="E2E-SEAT-WASA-GRO",
        office=wasa,
        designation_en="WASA Executive Engineer (GRO)",
        role_level=RoleLevel.GRO,
        incumbent_officer_id="E2E-EMP-WASA",
    )

    poly = MultiPolygon(
        Polygon(
            ((90.40, 23.78), (90.43, 23.78), (90.43, 23.81), (90.40, 23.81), (90.40, 23.78)),
            srid=4326,
        ),
        srid=4326,
    )
    zone = ServiceAreaPolygon.objects.create(
        zone_code="E2E-DNCC-W19",
        zone_type=ServiceAreaPolygon.ZoneType.CITY_CORP_WARD,
        bbs_geo_code="30262619",
        name_en="Gulshan Ward 19",
        primary_office=dncc,
        default_gro_seat=gro,
        geom=poly,
    )

    claims = get_identity_provider().exchange_code_for_claims("e2e-citizen-2026")
    citizen, profile = CitizenIdentityService.upsert_from_oidc_claims(claims)
    oversight = User.objects.create_user(
        username="e2e_oversight",
        account_type=User.AccountType.ARBITRATOR,
        doptor_seat_id="E2E-SEAT-OVERSIGHT",
        doptor_role_level=RoleLevel.APPELLATE,
        is_oversight_cell=True,
    )

    return {
        "dncc": dncc,
        "wasa": wasa,
        "appellate": appellate,
        "addl_gro": addl_gro,
        "gro": gro,
        "sup": sup,
        "fw": fw,
        "wasa_gro": wasa_gro,
        "zone": zone,
        "citizen": citizen,
        "profile": profile,
        "oversight": oversight,
        "point": Point(90.4143, 23.7925, srid=4326),
    }
