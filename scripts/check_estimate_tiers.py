#!/usr/bin/env python3
"""
Print per-part unit cost, price source tier, and review flags from a scan JSON.

Replaces the ad-hoc check_tiers (1).py script with CLI arguments.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _part_price_view(part: Dict[str, Any]) -> Dict[str, Any]:
    cost = float(part.get("unit_total_cost_gbp") or 0.0)
    cb = part.get("cost_breakdown") or {}
    sc = cb.get("system_cost") or {}
    me = part.get("material_estimate") or {}

    if sc.get("applied_to_total"):
        ps = sc.get("source") or {}
        src = ps.get("source_name") or ps.get("source") or "unknown"
        conf = float(ps.get("confidence") or 0.0)
        basis = ps.get("applied_basis") or ""
        note = f"UNIT £{float(sc.get('unit_cost_gbp') or 0):.4f} each"
        stock = (me.get("stock_form") or "") if me else ""
    else:
        ps = me.get("price_source") or {}
        src = ps.get("source_name") or ps.get("source") or "unknown"
        conf = float(ps.get("confidence") or 0.0)
        basis = ps.get("applied_basis") or me.get("cost_method") or ""
        wg = ps.get("stated_weight_kg")
        ws = ps.get("weight_source")
        mass = me.get("unit_material_mass_kg")
        note_parts = [str(basis) if basis else ""]
        if ws:
            note_parts.append(f"weight={ws}")
        if wg is not None:
            note_parts.append(f"{wg}kg")
        elif mass is not None:
            note_parts.append(f"{mass}kg calc")
        note = " ".join(p for p in note_parts if p)
        stock = me.get("stock_form") or ""

    review = bool(ps.get("review_required")) if isinstance(ps, dict) else False
    if part.get("risk_flags"):
        review = True

    return {
        "part_number": part.get("part_number", "?"),
        "unit_gbp": cost,
        "source": str(src)[:40],
        "confidence": conf,
        "note": (note or stock or "")[:60],
        "review": review,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-part estimate price source report")
    parser.add_argument(
        "json_path",
        nargs="?",
        default=str(ROOT / "output" / "json" / "12242-01-GA Vue Sprung Cup Holder_revD.json"),
        help="Scan summary JSON path",
    )
    parser.add_argument("--review-only", action="store_true", help="Only show lines flagged for review")
    args = parser.parse_args()

    path = Path(args.json_path)
    if not path.is_file():
        print(f"ERROR: not found: {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    parts: List[Dict[str, Any]] = data.get("estimate_summary", {}).get("part_estimates", [])
    if not parts:
        print("No part_estimates in JSON.")
        return 1

    print(f'{"Part":<22} {"£Unit":>7}  {"Source":<40} {"Conf":>5}  Note')
    print("-" * 95)

    for p in parts:
        row = _part_price_view(p)
        if args.review_only and not row["review"]:
            continue
        flag = " * REVIEW" if row["review"] else ""
        print(
            f"{row['part_number']:<22} £{row['unit_gbp']:>7.2f}  "
            f"{row['source']:<40} {row['confidence']:>5.2f}  {row['note']}{flag}"
        )

    print(f"\nParts: {len(parts)}  File: {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
