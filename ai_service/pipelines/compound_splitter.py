"""
Compound Complaint Splitter Pipeline.
Detects multi-agency narratives (e.g., burst WASA pipe + snapped DESCO pole + DNCC road/garbage)
and outputs sequenced Child Sub-Tickets (`step_order: 1 -> 2 -> 3`) with explicit dependencies.
"""

from __future__ import annotations

from typing import Any


class CompoundSplitterPipeline:
    """Builds sequenced execution plans when >=2 distinct agencies are predicted."""

    def build_plan(
        self, *, predictions: list[dict[str, Any]], narrative_en: str = "", narrative_bn: str = ""
    ) -> tuple[bool, list[dict[str, Any]]]:
        seen: set[str] = set()
        unique_preds: list[dict[str, Any]] = []
        for pred in sorted(predictions, key=lambda p: (p["step_order"], -p["confidence"])):
            if pred["agency_code"] not in seen:
                seen.add(pred["agency_code"])
                unique_preds.append(pred)

        if len(unique_preds) < 2:
            return False, []

        base_text = narrative_en or narrative_bn or "Compound civic incident"
        subtickets: list[dict[str, Any]] = []

        for idx, pred in enumerate(unique_preds, start=1):
            prev_pred = unique_preds[idx - 2] if idx > 1 else None
            depends_on = (idx - 1) if prev_pred else None
            dep_reason = (
                f"{prev_pred['agency_code']} ({prev_pred['category_code']}) must complete "
                f"before {pred['agency_code']} ({pred['category_code']}) begins."
                if prev_pred
                else "Unblocked Phase-1 immediate dispatch."
            )
            subtickets.append(
                {
                    "step_order": idx,
                    "agency_code": pred["agency_code"],
                    "ministry_code": pred["ministry_code"],
                    "category_code": pred["category_code"],
                    "zone_type": pred["zone_type"],
                    "urgency_tier": pred["urgency_tier"],
                    "summary_en": f"[{pred['agency_code']} Step {idx}] {base_text[:240]}",
                    "depends_on_step": depends_on,
                    "dependency_reason": dep_reason,
                }
            )
        return True, subtickets
