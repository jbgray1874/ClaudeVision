r"""
why_this_price.py — where did this line's number come from, in a page you can read.

WHY THIS EXISTS. 11650's sheet charged GBP 20.24 for 11650-05-02M SLIDER — 38% of the whole
material total — on a job whose own invariants said, in the same run:

    BLOCKING  bom_names_a_drawing_the_pack_does_not_contain: 11650-05-02M (SLIDER).
              Nothing read those parts, so nothing costed them

Both statements cannot be true. Answering which one was wrong meant dumping the part record,
and the record is thousands of lines of geometry, page roles, route decisions and raw
extract text. It could not be pasted, read or reasoned about, so the question went unanswered
while the number stayed on the sheet.

THE QUESTION IS NOT RARE. "Why is this line this price, and why is it in this block?" comes
up on every job, from the estimator as often as from us. It deserves a tool rather than a
one-off command, and the tool has to be GENERAL: it knows no field paths and no part numbers.
It finds every price stamp under the record by walking it — price_provenance.iter_price_stamps
already does exactly that, and does it because a checker that knew three field paths passed a
job whose only guessed price was in the fourth.

    python tools\diagnose\why_this_price.py 11650-05-02M
    python tools\diagnose\why_this_price.py 11650-05-02M 11650-05-01M --json <path>

Prints, per part: which workbook block it will land in and by which rule, what the price is
and what kind of source produced it, whether that money reached the total, and the handful of
fields the classification actually turns on. Nothing else.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))


def _newest_job_json(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit)
    import config
    candidates: List[str] = []
    for pattern in ("json/*.json", "estimates/*.json"):
        candidates += glob.glob(str(Path(config.OUTPUT_DIR) / pattern))
    # The LLM extract is a different document with a different shape; it is not the job.
    candidates = [c for c in candidates if "llm_extract" not in os.path.basename(c).lower()]
    if not candidates:
        raise SystemExit(f"No job JSON under {config.OUTPUT_DIR}. Pass --json <path>.")
    return Path(max(candidates, key=os.path.getmtime))


def _parts(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """part_estimates, wherever this document keeps them.

    Some writers stamp the estimate on the root and some inside estimate_summary. A reader
    that looks in one place reports "no such part" on every job of the other shape.
    """
    for holder in (doc.get("estimate_summary"), doc):
        if isinstance(holder, dict):
            pes = holder.get("part_estimates")
            if isinstance(pes, list) and pes:
                return [p for p in pes if isinstance(p, dict)]
    return []


# The classifier in wb_populate, stated as the questions it asks rather than copied. If it
# changes there this will disagree, and disagreeing loudly beats a stale copy that agrees
# with nothing -- the answer names the rule so a reader can check it against the sheet.
def _destination(pe: Dict[str, Any]) -> str:
    code = str(pe.get("part_number") or "").upper()
    me = pe.get("material_estimate") if isinstance(pe.get("material_estimate"), dict) else {}
    stock = str(me.get("stock_form") or pe.get("stock_form") or "").lower()
    roles = pe.get("page_roles") or []
    roles = [str(r).lower() for r in roles] if isinstance(roles, list) else [str(roles).lower()]
    blank = (me.get("blank") if isinstance(me.get("blank"), dict) else {}) or {}
    has_geom = any(blank.get(k) for k in ("length_mm", "width_mm")) or \
        any(pe.get(k) for k in ("blank_length_mm", "blank_width_mm"))
    if code in {"PACKAGING", "DELIVERY"}:
        return "DROPPED (rule 1: placeholder — estimator adds it manually)"
    if pe.get("_suppressed") or pe.get("is_assembly"):
        return "LABOUR ONLY (rule 2: assembly/weldment parent — excluded from material)"
    if stock in {"sheet", "stated_weight"} and has_geom:
        return "Sheet Steel block (rule 3: sheet stock with geometry — WB computes LxWxgauge)"
    if stock == "tube":
        return "BOM (rule 4: tube — catalogue-priced section)"
    if "bought_in" in roles:
        return "BOM (rule 5: page role says bought_in — priced from unit_cost_gbp)"
    if str(me.get("material_class") or "").lower() in {"board", "plastic", "acrylic"}:
        return "Other Sheet Material block (rule 6: board material)"
    if has_geom:
        return "Sheet Steel block (rule 7: has blank geometry)"
    return ("BOM (rule 8: NO page role, NO geometry — priced from an external cost. "
            "THIS IS THE CATCH-ALL: a part that reaches it was never read as anything.")


_INTERESTING = (
    "part_number", "description", "quantity", "unit_cost_gbp", "stock_form",
    "page_roles", "material_class", "supplier_name", "matched_part_code",
    "_bom_cross_reference", "_duplicate_of", "_price_explicitly_withheld",
    "_consumable_qty_unknown", "_catalogue_rate_gbp", "assembly_only",
)


def _facts(pe: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    me = pe.get("material_estimate") if isinstance(pe.get("material_estimate"), dict) else {}
    for key in _INTERESTING:
        for src in (pe, me):
            if key in src and src[key] not in (None, "", [], {}):
                out[key] = src[key]
                break
    return out


def _report(pe: Dict[str, Any]) -> None:
    import price_provenance as pp
    code = pe.get("part_number")
    print(f"\n{'=' * 78}\n{code}   {str(pe.get('description') or '')[:56]}\n{'=' * 78}")
    print(f"  GOES TO   {_destination(pe)}")
    for key, value in _facts(pe).items():
        if key in ("part_number", "description"):
            continue
        print(f"  {key:<28} {str(value)[:70]}")

    # HOW THE MATERIAL FIGURE WAS ARRIVED AT. Knowing WHICH FIELD supplied a price is half
    # the answer; the other half is where the number in that field came from. 11650-05-02M's
    # GBP 9.73 was traced to material_estimate.unit_material_cost_gbp and then guessed at
    # twice, because nothing showed the mass, the rate, the area or the method behind it.
    me = pe.get("material_estimate") if isinstance(pe.get("material_estimate"), dict) else {}
    if me:
        print("\n  MATERIAL ESTIMATE")
        for key in ("cost_method", "material", "unit_material_mass_kg", "blank_area_m2",
                    "blank_length_mm", "blank_width_mm", "thickness_mm",
                    "unit_material_cost_gbp", "cost_per_part_gbp",
                    "extended_material_cost_gbp", "extended_sheet_material_cost_gbp"):
            if key in me:
                print(f"    {key:<32} {me[key]!r}")
        pc = me.get("powder_consumable")
        if isinstance(pc, dict):
            # POWDER IS COMBINED INTO extended_material_cost_gbp, so it can appear in a
            # material figure without appearing in any material field.
            print(f"    powder_consumable                "
                  + ", ".join(f"{k}={v!r}" for k, v in list(pc.items())[:6]))
        se = me.get("stock_estimate")
        if isinstance(se, dict):
            print(f"    stock_estimate                   "
                  + ", ".join(f"{k}={v!r}" for k, v in list(se.items())[:6]))

    # THE PRICE CHAIN, FROM THE FUNCTION THAT DECIDES IT.
    #
    # Not re-implemented here. A second copy of the waterfall would be a second rule for one
    # question and would drift from the sheet -- and the whole reason this section exists is
    # that GBP 9.73 was refused at one field and walked back in at the next, with nothing
    # able to say which of five fields had supplied it.
    try:
        from wb_populate import _bom_line_price_traced
        price, chain = _bom_line_price_traced(pe)
        print(f"\n  BOM PRICE  {'£%.4f' % price if price is not None else 'UNPRICED'}")
        for step in chain:
            print(f"    {step}")
    except Exception as exc:                                 # noqa: BLE001
        print(f"\n  BOM PRICE  could not be traced ({type(exc).__name__}: {exc})")

    stamps = list(pp.iter_price_stamps(pe))
    if not stamps:
        print("\n  NO PRICE STAMP ANYWHERE UNDER THIS PART.")
        print("  A price with no stamp cannot be attributed, and a line the sheet charges")
        print("  for with nothing saying where the figure came from is the thing this")
        print("  engine exists to stop. If the sheet shows money on this line, that money")
        print("  was written by something that did not record itself.")
        return
    print(f"\n  {len(stamps)} price stamp(s):")
    for path, block in stamps:
        print(f"    {path or '(root)'}")
        print(f"      source        {block.get('source') or block.get('source_name') or '?'}"
              f"   class={pp.stamp_source_class(block)}")
        print(f"      reproducible  {pp.stamp_is_reproducible(block)}"
              f"    reached the total  {pp.stamp_affects_total(block)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("parts", nargs="+", help="part number(s), case-insensitive")
    ap.add_argument("--json", help="job JSON (default: the newest under OUTPUT_DIR)")
    args = ap.parse_args()

    path = _newest_job_json(args.json)
    print(f"reading {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    parts = _parts(doc)
    if not parts:
        raise SystemExit("That document holds no part_estimates.")

    wanted = {p.strip().upper() for p in args.parts}
    seen = set()
    for pe in parts:
        code = str(pe.get("part_number") or "").strip().upper()
        if code in wanted:
            seen.add(code)
            _report(pe)
    # A PART THAT IS NOT THERE IS AN ANSWER, not an empty page. "No output" reads as "the
    # tool is broken"; it usually means the code on the sheet is not the code on the record.
    for missing in sorted(wanted - seen):
        print(f"\n{'=' * 78}\n{missing}\n{'=' * 78}")
        print(f"  NOT IN part_estimates ({len(parts)} parts on this job).")
        near = [str(p.get("part_number")) for p in parts
                if missing[:9] in str(p.get("part_number") or "").upper()]
        if near:
            print(f"  Similar codes present: {', '.join(near[:8])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
