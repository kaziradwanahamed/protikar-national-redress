"""
Bulk KML / GeoJSON Service-Area Polygon Importer for PostGIS `ServiceAreaPolygon`.
Ingests City Corporation Wards, WASA MODS zones, DESCO/DPDC feeders, and RHD/LGED corridors.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.organogram.models import DoptorOffice, DoptorSeat, ServiceAreaPolygon


def _to_multipolygon(geom: GEOSGeometry) -> MultiPolygon:
    if geom.geom_type == "Polygon":
        mp = MultiPolygon(geom, srid=4326)
    elif geom.geom_type == "MultiPolygon":
        mp = geom
        mp.srid = 4326
    else:
        raise ValueError(f"Unsupported geometry type '{geom.geom_type}'; expected Polygon or MultiPolygon.")
    return mp


def _parse_kml_coordinates(coord_text: str) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for token in (coord_text or "").strip().split():
        parts = token.split(",")
        if len(parts) >= 2:
            pts.append((float(parts[0]), float(parts[1])))
    if pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    return pts


def parse_geojson_features(file_path: Path) -> list[dict]:
    data = json.loads(file_path.read_text(encoding="utf-8"))
    features = data.get("features") if data.get("type") == "FeatureCollection" else [data]
    parsed = []
    for idx, feat in enumerate(features, start=1):
        props = feat.get("properties") or {}
        geom_json = feat.get("geometry")
        if not geom_json:
            continue
        geom = _to_multipolygon(GEOSGeometry(json.dumps(geom_json), srid=4326))
        parsed.append({"index": idx, "properties": props, "geom": geom})
    return parsed


def parse_kml_features(file_path: Path) -> list[dict]:
    tree = ET.parse(file_path)
    root = tree.getroot()
    ns_uri = root.tag.split("}")[0].strip("{") if "}" in root.tag else ""
    ns = {"kml": ns_uri} if ns_uri else {}
    prefix = "kml:" if ns_uri else ""

    parsed = []
    for idx, placemark in enumerate(root.findall(f".//{prefix}Placemark", ns), start=1):
        name_el = placemark.find(f"{prefix}name", ns)
        props = {"name_en": name_el.text.strip() if (name_el is not None and name_el.text) else f"Zone {idx}"}
        for data_el in placemark.findall(f".//{prefix}Data", ns):
            k = data_el.attrib.get("name")
            v_el = data_el.find(f"{prefix}value", ns)
            if k and v_el is not None and v_el.text:
                props[k] = v_el.text.strip()
        for simple_el in placemark.findall(f".//{prefix}SimpleData", ns):
            k = simple_el.attrib.get("name")
            if k and simple_el.text:
                props[k] = simple_el.text.strip()

        polys = []
        for poly_el in placemark.findall(f".//{prefix}Polygon", ns):
            coord_el = poly_el.find(f".//{prefix}outerBoundaryIs/{prefix}LinearRing/{prefix}coordinates", ns)
            if coord_el is not None and coord_el.text:
                ring = _parse_kml_coordinates(coord_el.text)
                if len(ring) >= 4:
                    polys.append(Polygon(ring, srid=4326))
        if polys:
            parsed.append({"index": idx, "properties": props, "geom": MultiPolygon(*polys, srid=4326)})
    return parsed


class Command(BaseCommand):
    help = "Bulk import KML or GeoJSON administrative/utility polygons into PostGIS ServiceAreaPolygon."

    def add_arguments(self, parser):
        parser.add_argument("file_path", type=str, help="Path to .geojson, .json, or .kml file.")
        parser.add_argument(
            "--zone-type",
            type=str,
            default=ServiceAreaPolygon.ZoneType.CITY_CORP_WARD,
            choices=[c[0] for c in ServiceAreaPolygon.ZoneType.choices],
            help="Default ServiceAreaPolygon.ZoneType if not specified per feature.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate & parse without committing to DB.")

    def handle(self, *args, **options):
        path = Path(options["file_path"])
        if not path.exists():
            raise CommandError(f"GIS file not found: {path}")

        suffix = path.suffix.lower()
        if suffix in (".geojson", ".json"):
            features = parse_geojson_features(path)
        elif suffix == ".kml":
            features = parse_kml_features(path)
        else:
            raise CommandError(f"Unsupported file format '{suffix}'. Use .geojson, .json, or .kml.")

        created_count = 0
        updated_count = 0
        default_zone_type = options["zone_type"]

        with transaction.atomic():
            for item in features:
                props = item["properties"]
                zone_code = str(props.get("zone_code") or f"{default_zone_type}-{item['index']:04d}")
                zone_type = str(props.get("zone_type") or default_zone_type)
                office = (
                    DoptorOffice.objects.filter(office_code=props["office_code"]).first()
                    if props.get("office_code")
                    else None
                )
                gro_seat = (
                    DoptorSeat.objects.filter(doptor_seat_id=props["gro_seat_id"]).first()
                    if props.get("gro_seat_id")
                    else None
                )
                _obj, created = ServiceAreaPolygon.objects.update_or_create(
                    zone_code=zone_code,
                    defaults={
                        "zone_type": zone_type,
                        "bbs_geo_code": str(props.get("bbs_geo_code", "")),
                        "name_en": str(props.get("name_en") or zone_code),
                        "name_bn": str(props.get("name_bn", "")),
                        "primary_office": office,
                        "default_gro_seat": gro_seat,
                        "geom": item["geom"],
                        "metadata": {k: v for k, v in props.items() if k not in ("zone_code", "name_en", "name_bn")},
                        "is_active": True,
                    },
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1

            if options["dry_run"]:
                transaction.set_rollback(True)

        mode = "DRY-RUN" if options["dry_run"] else "COMMITTED"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] Processed {len(features)} polygons from {path.name}: "
                f"created={created_count}, updated={updated_count}."
            )
        )
