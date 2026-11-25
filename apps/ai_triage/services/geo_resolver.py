"""
PostGIS Jurisdiction Resolver + Bangla Geo-NER Extractor.

Intersects complaint `geo_point` + Bangla/English Geo-NER place entities against
`ServiceAreaPolygon` (BBS Geo-Codes, City Corp Wards, WASA MODS, DESCO/DPDC feeders,
RHD vs. LGED road corridors).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.contrib.gis.geos import Point

from apps.organogram.models import ServiceAreaPolygon


BANGLA_GEO_GAZETTEER: dict[str, dict] = {
    "গুলশান": {"name_en": "Gulshan", "bbs_geo_code": "30262619", "lon": 90.4143, "lat": 23.7925},
    "gulshan": {"name_en": "Gulshan", "bbs_geo_code": "30262619", "lon": 90.4143, "lat": 23.7925},
    "বনানী": {"name_en": "Banani", "bbs_geo_code": "30262619", "lon": 90.4043, "lat": 23.7937},
    "banani": {"name_en": "Banani", "bbs_geo_code": "30262619", "lon": 90.4043, "lat": 23.7937},
    "মিরপুর": {"name_en": "Mirpur", "bbs_geo_code": "302648", "lon": 90.3687, "lat": 23.8069},
    "mirpur": {"name_en": "Mirpur", "bbs_geo_code": "302648", "lon": 90.3687, "lat": 23.8069},
    "মতিঝিল": {"name_en": "Motijheel", "bbs_geo_code": "30265420", "lon": 90.4175, "lat": 23.7330},
    "motijheel": {"name_en": "Motijheel", "bbs_geo_code": "30265420", "lon": 90.4175, "lat": 23.7330},
    "সাভার": {"name_en": "Savar", "bbs_geo_code": "302672", "lon": 90.2667, "lat": 23.8583},
    "savar": {"name_en": "Savar", "bbs_geo_code": "302672", "lon": 90.2667, "lat": 23.8583},
    "আশুলিয়া": {"name_en": "Ashulia", "bbs_geo_code": "302672", "lon": 90.3200, "lat": 23.8950},
    "ashulia": {"name_en": "Ashulia", "bbs_geo_code": "302672", "lon": 90.3200, "lat": 23.8950},
    "যাত্রাবাড়ী": {"name_en": "Jatrabari", "bbs_geo_code": "3026", "lon": 90.4400, "lat": 23.7100},
    "jatrabari": {"name_en": "Jatrabari", "bbs_geo_code": "3026", "lon": 90.4400, "lat": 23.7100},
}


@dataclass(frozen=True)
class JurisdictionResolution:
    resolved_point: Point | None
    bbs_geo_code: str
    extracted_geo_entities: list[str] = field(default_factory=list)
    matched_zones: list[ServiceAreaPolygon] = field(default_factory=list)
    seat_by_zone_type: dict[str, str] = field(default_factory=dict)


class PostGISJurisdictionResolver:
    """Combines Bangla/English Geo-NER with PostGIS ST_Contains polygon intersection."""

    @staticmethod
    def extract_geo_entities(text_bn: str = "", text_en: str = "") -> tuple[list[str], dict | None]:
        combined = f"{text_bn} {text_en}".lower()
        found: list[str] = []
        primary_meta = None
        for token, meta in BANGLA_GEO_GAZETTEER.items():
            if token in combined:
                if meta["name_en"] not in found:
                    found.append(meta["name_en"])
                if primary_meta is None:
                    primary_meta = meta
        return found, primary_meta

    @classmethod
    def resolve(
        cls,
        *,
        geo_point: Point | None,
        text_bn: str = "",
        text_en: str = "",
    ) -> JurisdictionResolution:
        entities, ner_meta = cls.extract_geo_entities(text_bn, text_en)
        effective_point = geo_point
        if effective_point is None and ner_meta is not None:
            effective_point = Point(ner_meta["lon"], ner_meta["lat"], srid=4326)

        matched_zones: list[ServiceAreaPolygon] = []
        seat_by_zone_type: dict[str, str] = {}
        bbs_code = ner_meta["bbs_geo_code"] if ner_meta else ""

        if effective_point is not None:
            qs = (
                ServiceAreaPolygon.objects.select_related("primary_office", "default_gro_seat")
                .filter(is_active=True, geom__contains=effective_point)
                .order_by("zone_type")
            )
            matched_zones = list(qs)
            for zone in matched_zones:
                if zone.default_gro_seat:
                    seat_by_zone_type[zone.zone_type] = zone.default_gro_seat.doptor_seat_id
                # Prefer most specific (longest) BBS geocode from PostGIS polygon match
                if len(zone.bbs_geo_code or "") > len(bbs_code):
                    bbs_code = zone.bbs_geo_code

        return JurisdictionResolution(
            resolved_point=effective_point,
            bbs_geo_code=bbs_code,
            extracted_geo_entities=entities,
            matched_zones=matched_zones,
            seat_by_zone_type=seat_by_zone_type,
        )

    @staticmethod
    def pick_seat_for_zone_type(
        resolution: JurisdictionResolution, preferred_zone_type: str
    ) -> str | None:
        if preferred_zone_type in resolution.seat_by_zone_type:
            return resolution.seat_by_zone_type[preferred_zone_type]
        for fallback_type in (
            ServiceAreaPolygon.ZoneType.CITY_CORP_WARD,
            ServiceAreaPolygon.ZoneType.BBS_UPAZILA,
            ServiceAreaPolygon.ZoneType.BBS_DISTRICT,
        ):
            if fallback_type in resolution.seat_by_zone_type:
                return resolution.seat_by_zone_type[fallback_type]
        return next(iter(resolution.seat_by_zone_type.values()), None)
