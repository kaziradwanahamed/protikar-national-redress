"""NFR06: Backup & Recovery snapshot command exporting JSON/SQL-ready archive into backups/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from apps.complaints.models import (
    AuditLog,
    CitizenNotification,
    Complaint,
    ComplaintProgressUpdate,
    ResolutionReport,
    TicketAssignment,
)
from apps.esb.models import AgencyEndpoint
from apps.organogram.models import DoptorOffice, DoptorSeat, ServiceAreaPolygon


class Command(BaseCommand):
    help = "NFR06: Export timestamped JSON backup snapshot of complaints, audit ledger, and GIS polygons into backups/."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            default=str(Path(settings.BASE_DIR) / "backups"),
            help="Target directory for backup snapshots (default: <BASE_DIR>/backups).",
        )

    def handle(self, *args, **options):
        out_dir = Path(options["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = timezone.now().strftime("%Y%m%d_%H%M%S")
        snapshot_path = out_dir / f"protikar_backup_{ts}.json"

        complaints_data = []
        for c in Complaint.objects.all().order_by("created_at"):
            complaints_data.append(
                {
                    "complaint_id": str(c.complaint_id),
                    "tracking_code": c.tracking_code,
                    "status": c.status,
                    "urgency_tier": c.urgency_tier,
                    "ai_category_code": c.ai_category_code,
                    "admin_geo_code": c.admin_geo_code,
                    "geo_wkt": c.geo_point.wkt if c.geo_point else None,
                    "raw_text_en": c.raw_text_en,
                    "raw_text_bn": c.raw_text_bn,
                    "created_at": c.created_at,
                    "updated_at": c.updated_at,
                }
            )

        payload = {
            "platform": "Protikar National Redress (প্রতিকার — জাতীয় অভিযোগ প্রতিকার প্ল্যাটফর্ম)",
            "exported_at": timezone.now(),
            "counts": {
                "complaints": len(complaints_data),
                "assignments": TicketAssignment.objects.count(),
                "resolution_reports": ResolutionReport.objects.count(),
                "progress_updates": ComplaintProgressUpdate.objects.count(),
                "notifications": CitizenNotification.objects.count(),
                "audit_logs": AuditLog.objects.count(),
                "doptor_offices": DoptorOffice.objects.count(),
                "doptor_seats": DoptorSeat.objects.count(),
                "gis_polygons": ServiceAreaPolygon.objects.count(),
                "esb_endpoints": AgencyEndpoint.objects.count(),
            },
            "complaints": complaints_data,
            "assignments": list(TicketAssignment.objects.values()),
            "resolution_reports": list(ResolutionReport.objects.values()),
            "progress_updates": list(ComplaintProgressUpdate.objects.values()),
            "notifications": list(CitizenNotification.objects.values()),
            "audit_logs": list(AuditLog.objects.order_by("sequence_no").values()),
            "doptor_offices": list(DoptorOffice.objects.values()),
            "doptor_seats": list(DoptorSeat.objects.values()),
            "gis_polygons": [
                {
                    "polygon_id": str(p.polygon_id),
                    "service_domain": p.service_domain,
                    "bbs_geo_code": p.bbs_geo_code,
                    "name_en": p.name_en,
                    "name_bn": p.name_bn,
                    "geom_wkt": p.geom.wkt if p.geom else None,
                }
                for p in ServiceAreaPolygon.objects.all()
            ],
            "esb_endpoints": list(AgencyEndpoint.objects.values("agency_code", "agency_name", "tier", "last_synced_at", "is_active")),
        }

        serialized = json.dumps(payload, cls=DjangoJSONEncoder, indent=2, ensure_ascii=False)
        snapshot_path.write_text(serialized, encoding="utf-8")
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        checksum_path = out_dir / f"protikar_backup_{ts}.sha256"
        checksum_path.write_text(f"{digest}  {snapshot_path.name}\n", encoding="utf-8")

        self.stdout.write(
            self.style.SUCCESS(
                f"Backup snapshot written: {snapshot_path} ({len(serialized):,} bytes, SHA-256={digest[:16]}...)"
            )
        )
