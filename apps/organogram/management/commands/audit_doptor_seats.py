"""
Doptor Seat Audit Command (`python manage.py audit_doptor_seats`).
Detects vacant seats lacking `additional_charge_seat_id`, double-vacancies,
broken supervisor-to-field reporting chains, cycles, and inverted role levels.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.organogram.models import DoptorSeat, RoleLevel


ROLE_RANK = {
    RoleLevel.FIELD_WORKER: 1,
    RoleLevel.SUPERVISOR: 2,
    RoleLevel.GRO: 3,
    RoleLevel.APPELLATE: 4,
}


class Command(BaseCommand):
    help = "Audits DoptorSeat vacancy fallbacks and supervisor-to-field reporting chains."

    def add_arguments(self, parser):
        parser.add_argument("--output", type=str, default="", help="Optional path to write JSON audit report.")
        parser.add_argument(
            "--fail-on-error",
            action="store_true",
            help="Exit with non-zero status if critical organogram hygiene issues are found.",
        )

    def handle(self, *args, **options):
        seats = list(
            DoptorSeat.objects.select_related("office", "parent_seat", "additional_charge_seat").filter(
                is_active=True
            )
        )

        vacant_no_addl: list[dict] = []
        double_vacant: list[dict] = []
        orphan_chains: list[dict] = []
        cycle_errors: list[dict] = []
        inverted_hierarchy: list[dict] = []

        seat_map = {s.seat_id: s for s in seats}

        for seat in seats:
            # 1. Vacant seat checks
            if not seat.is_occupied:
                if seat.additional_charge_seat is None:
                    vacant_no_addl.append(
                        {
                            "doptor_seat_id": seat.doptor_seat_id,
                            "office_code": seat.office.office_code,
                            "role_level": seat.role_level,
                            "immediate_supervisor_seat_id": seat.immediate_supervisor_seat_id,
                        }
                    )
                elif not seat.additional_charge_seat.is_occupied:
                    double_vacant.append(
                        {
                            "doptor_seat_id": seat.doptor_seat_id,
                            "additional_charge_seat_id": seat.additional_charge_seat.doptor_seat_id,
                        }
                    )

            # 2. Supervisor-to-field reporting chain checks
            if seat.role_level != RoleLevel.APPELLATE and seat.parent_seat is None:
                orphan_chains.append(
                    {
                        "doptor_seat_id": seat.doptor_seat_id,
                        "office_code": seat.office.office_code,
                        "role_level": seat.role_level,
                        "issue": "Non-Appellate seat has no immediate_supervisor_seat (parent_seat).",
                    }
                )

            if seat.parent_seat:
                child_rank = ROLE_RANK.get(seat.role_level, 0)
                parent_rank = ROLE_RANK.get(seat.parent_seat.role_level, 0)
                if parent_rank < child_rank:
                    inverted_hierarchy.append(
                        {
                            "doptor_seat_id": seat.doptor_seat_id,
                            "role_level": seat.role_level,
                            "parent_seat_id": seat.parent_seat.doptor_seat_id,
                            "parent_role_level": seat.parent_seat.role_level,
                        }
                    )

            # 3. Cycle detection in parent_seat chain
            visited = {seat.seat_id}
            cursor_id = seat.parent_seat_id
            while cursor_id:
                if cursor_id in visited:
                    cycle_errors.append({"doptor_seat_id": seat.doptor_seat_id})
                    break
                visited.add(cursor_id)
                nxt = seat_map.get(cursor_id)
                cursor_id = nxt.parent_seat_id if nxt else None

        report = {
            "total_active_seats": len(seats),
            "vacant_without_additional_charge": vacant_no_addl,
            "double_vacant_additional_charge": double_vacant,
            "orphan_reporting_chains": orphan_chains,
            "inverted_role_hierarchies": inverted_hierarchy,
            "reporting_cycles": cycle_errors,
            "total_findings": (
                len(vacant_no_addl)
                + len(double_vacant)
                + len(orphan_chains)
                + len(inverted_hierarchy)
                + len(cycle_errors)
            ),
        }

        if options["output"]:
            out_path = Path(options["output"])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

        self.stdout.write(
            f"Doptor Seat Audit Summary: active={len(seats)}, "
            f"vacant_no_addl={len(vacant_no_addl)}, double_vacant={len(double_vacant)}, "
            f"orphan_chains={len(orphan_chains)}, inverted={len(inverted_hierarchy)}, "
            f"cycles={len(cycle_errors)}."
        )

        if options["fail_on_error"] and report["total_findings"] > 0:
            raise CommandError(f"Doptor Seat Audit failed with {report['total_findings']} finding(s).")
