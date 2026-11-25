"""
Shadow-Routing Dry Run Simulator (`python manage.py run_shadow_routing --file historical_grs.json`).
Replays 5,000+ historical GRS/utility complaints through the AI + PostGIS router in zero-write
dry-run mode and exports a misroute & boundary-conflict audit report (CSV / JSON).
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError

from apps.ai_triage.services.classifier import HierarchicalMultiLabelClassifier
from apps.ai_triage.services.geo_resolver import PostGISJurisdictionResolver


def _load_records(file_path: Path, limit: int | None = None) -> list[dict]:
    text = file_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if text.startswith("["):
        records = json.loads(text)
    else:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    return records[:limit] if limit else records


class Command(BaseCommand):
    help = (
        "Replays historical GRS/utility complaints through AI + PostGIS routing in zero-write "
        "dry-run mode and exports misroute & boundary-conflict audit reports (CSV/JSON)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, type=str, help="Path to historical_grs.json or .jsonl")
        parser.add_argument("--output-csv", type=str, default="shadow_routing_audit.csv")
        parser.add_argument("--output-json", type=str, default="shadow_routing_summary.json")
        parser.add_argument("--limit", type=int, default=0, help="Optional max records to replay (0 = all).")

    def handle(self, *args, **options):
        src = Path(options["file"])
        if not src.exists():
            raise CommandError(f"Historical GRS dataset not found: {src}")

        records = _load_records(src, limit=options["limit"] or None)
        classifier = HierarchicalMultiLabelClassifier()

        audit_rows: list[dict] = []
        decision_counts: Counter[str] = Counter()
        misroute_count = 0
        boundary_conflict_count = 0
        matched_count = 0

        for idx, rec in enumerate(records, start=1):
            case_id = str(rec.get("id") or f"HIST-{idx:05d}")
            text_bn = str(rec.get("text_bn", ""))
            text_en = str(rec.get("text_en", ""))
            expected_agency = str(rec.get("expected_agency_code", "")).upper()
            lat = rec.get("lat")
            lon = rec.get("lon")
            point = Point(float(lon), float(lat), srid=4326) if (lat is not None and lon is not None) else None

            clf_out = classifier.classify(text_bn=text_bn, text_en=text_en)
            jurisdiction = PostGISJurisdictionResolver.resolve(
                geo_point=point, text_bn=text_bn, text_en=text_en
            )

            predicted_agency = clf_out.predictions[0].agency_code if clf_out.predictions else "UNCLASSIFIED"
            decision_counts[clf_out.routing_decision] += 1

            # Detect misroutes vs historical agency label
            is_misroute = bool(expected_agency and predicted_agency != expected_agency)
            if is_misroute:
                misroute_count += 1
            elif expected_agency:
                matched_count += 1

            # Detect PostGIS boundary conflicts (multiple zones of identical zone_type or zero polygon hit)
            zone_type_counts = Counter(z.zone_type for z in jurisdiction.matched_zones)
            duplicate_zone_types = [zt for zt, cnt in zone_type_counts.items() if cnt > 1]
            boundary_conflict = ""
            if duplicate_zone_types:
                boundary_conflict = f"OVERLAPPING_POLYGONS:{','.join(duplicate_zone_types)}"
                boundary_conflict_count += 1
            elif point is not None and not jurisdiction.matched_zones:
                boundary_conflict = "OUTSIDE_SEEDED_POLYGONS"
                boundary_conflict_count += 1

            audit_rows.append(
                {
                    "case_id": case_id,
                    "expected_agency": expected_agency,
                    "predicted_agency": predicted_agency,
                    "confidence": clf_out.top_confidence,
                    "routing_decision": clf_out.routing_decision,
                    "is_misroute": is_misroute,
                    "bbs_geo_code": jurisdiction.bbs_geo_code,
                    "matched_zones": "|".join(z.zone_code for z in jurisdiction.matched_zones),
                    "boundary_conflict": boundary_conflict,
                }
            )

        total = len(audit_rows)
        labeled_total = matched_count + misroute_count
        accuracy_pct = round((matched_count / labeled_total) * 100.0, 2) if labeled_total else 0.0

        # Export CSV
        csv_path = Path(options["output_csv"])
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "case_id",
                    "expected_agency",
                    "predicted_agency",
                    "confidence",
                    "routing_decision",
                    "is_misroute",
                    "bbs_geo_code",
                    "matched_zones",
                    "boundary_conflict",
                ],
            )
            writer.writeheader()
            writer.writerows(audit_rows)

        # Export JSON summary
        summary = {
            "source_file": str(src),
            "total_replayed": total,
            "labeled_total": labeled_total,
            "matched_count": matched_count,
            "misroute_count": misroute_count,
            "accuracy_pct": accuracy_pct,
            "boundary_conflict_count": boundary_conflict_count,
            "routing_decision_breakdown": dict(decision_counts),
            "csv_report_path": str(csv_path),
        }
        json_path = Path(options["output_json"])
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"[SHADOW DRY-RUN] Replayed {total} complaints | Accuracy={accuracy_pct}% | "
                f"Misroutes={misroute_count} | BoundaryConflicts={boundary_conflict_count} | "
                f"CSV={csv_path} | JSON={json_path}"
            )
        )
