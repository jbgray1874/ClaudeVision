#!/usr/bin/env python3
r"""
_1310_dave_diag.py — read-only. Answers Dave's three points with data, not with my opinion.

  1. P.Coat qty 2 — should be ONE welded assembly
  2. Width 113mm where the drawing says 105mm — where is 113 coming from?
  3. No powder on the estimate — is it because no powder is named on the drawing?

Writes nothing. Touches no production code.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _1310_dave_diag.py
"""
from __future__ import annotations
import json, glob, os, sys

JSON_DIR = r"C:\ClaudeVision\output\json"


def find_json():
    hits = [p for p in glob.glob(os.path.join(JSON_DIR, "*.json")) if "1310" in os.path.basename(p)]
    if not hits:
        sys.exit(f"no 1310 json under {JSON_DIR}")
    return max(hits, key=os.path.getmtime)


def show(label, val, indent=6):
    print(" " * indent + f"{label:<34} {val}")


def main():
    p = find_json()
    print(f"\n  {p}\n")
    d = json.load(open(p, encoding="utf-8"))

    pes = ((d.get("estimate_summary") or {}).get("part_estimates")
           or d.get("parts") or [])
    mw = (d.get("manufacturing_writeup") or {}).get("parts") or []
    mw_by_pn = {str(m.get("part_number") or ""): m for m in mw}

    # ── POINT 2 — WHERE DOES THE WIDTH COME FROM? ────────────────────────────
    print("=" * 78)
    print("  POINT 2 — GEOMETRY PROVENANCE (Dave: '113mm instead of 105mm')")
    print("=" * 78)
    print("  wb_populate writes:  width = material_estimate.blank_width_mm")
    print("                            or normalized_geometry.blank_width_mm")
    print("  A DXF is a FLAT PATTERN. If 113 is the BLANK and 105 is the FORMED")
    print("  width, the engine may be RIGHT — you cut 113mm from the sheet.")
    print("  2mm material, 2 bends, ~4mm deduction each = 8mm.  113 - 105 = 8.")
    print("  But 8mm is ALSO the stud diameter on 1310-02. Do not assume — read it.\n")

    for pe in pes:
        pn = pe.get("part_number") or "(none)"
        me = pe.get("material_estimate") or {}
        ng = pe.get("normalized_geometry") or {}
        gr = pe.get("geometry_rollup") or {}
        print(f"  ── {pn}  {pe.get('description') or ''}")
        show("stock_form", me.get("stock_form"))
        show("thickness_mm", pe.get("normalized_thickness_mm") or me.get("thickness_mm"))
        print()
        show("me.blank_length_mm", me.get("blank_length_mm"))
        show("me.blank_width_mm", me.get("blank_width_mm"))
        show("ng.blank_length_mm", ng.get("blank_length_mm"))
        show("ng.blank_width_mm", ng.get("blank_width_mm"))
        print()
        show("gr.cut_length_mm", gr.get("cut_length_mm") or ng.get("cut_length_mm"))
        show("gr.bend_count", gr.get("bend_count") or ng.get("bend_count"))
        show("gr.estimated_hole_count", gr.get("estimated_hole_count"))
        show("geometry_source", pe.get("geometry_source") or ng.get("source") or me.get("source"))
        show("dxf_path", (pe.get("dxf_path") or ng.get("dxf_path") or "—"))
        # anything that smells like a raw bounding box
        for k, v in list(ng.items()) + list(gr.items()):
            if any(t in str(k).lower() for t in ("bbox", "bound", "extent", "raw_", "min_", "max_")):
                show(f"  {k}", v)
        print()

    # ── POINT 1 — WELD / FINISH / P.COAT QTY ─────────────────────────────────
    print("=" * 78)
    print("  POINT 1 — IS THIS ONE WELDED ASSEMBLY?  (Dave: P.Coat should be qty 1)")
    print("=" * 78)
    print("  RULE WE SHOULD BE APPLYING:")
    print("     parts joined by a WELD become ONE object -> ONE trip through the booth.")
    print("  We built this yesterday for 7670 but gated it on 'does anything ELSE in the")
    print("  job qualify for powder' — which is the wrong question. Welding is the signal.\n")

    for pn, m in mw_by_pn.items():
        ops = m.get("textual_operations") or m.get("operations") or []
        fins = m.get("surface_finishes") or []
        print(f"  ── {pn}")
        show("normalized_finish", m.get("normalized_finish"))
        show("surface_finishes", fins)
        show("operations", ops)
        _welds = [o for o in ops if "weld" in str(o).lower()]
        show("WELD OPS ON THIS PART", _welds if _welds else "— none —")
        print()

    _all_ops = []
    for m in mw:
        _all_ops += [str(o) for o in (m.get("textual_operations") or m.get("operations") or [])]
    _job_welds = sorted({o for o in _all_ops if "weld" in o.lower()})
    print(f"  WELD OPERATIONS ANYWHERE ON THE JOB: {_job_welds or '— none —'}")
    print("  If this job welds, the coated object is the WELDMENT, not the components.\n")

    # ── POINT 3 — POWDER ─────────────────────────────────────────────────────
    print("=" * 78)
    print("  POINT 3 — POWDER MATERIAL  (Dave: 'no specific powder on the drawing'?)")
    print("=" * 78)
    print("  Two SEPARATE powder costs, and they come from different places:")
    print("     LABOUR   P.Coat row   -> rate card x throughput      (this one fired)")
    print("     MATERIAL powder kg    -> WB Powder Qty Calculator")
    print("                              = sheet area x 0.1667 kg/m2 x POWDER_COST_PER_KG")
    print("  The MATERIAL does NOT need a powder code on the drawing — it is computed")
    print("  from area. So if it is zero, Dave's hypothesis is WRONG and something else")
    print("  is broken. If it is small-but-nonzero, it is the COVERAGE RATE (0.1667 kg/m2")
    print("  = 100% transfer efficiency, which nothing achieves — Tim's sheets imply")
    print("  0.45-1.70). We shipped 1310 at 6p against Tim's 30p.\n")

    _powder_bom = [pe for pe in pes
                   if "POWDER" in str(pe.get("part_number") or "").upper()
                   or "POWDER" in str(pe.get("description") or "").upper()]
    show("powder line in the BOM?", f"{len(_powder_bom)} found", 2)
    for pe in _powder_bom:
        show("  part_number", pe.get("part_number"), 4)
        show("  description", str(pe.get("description"))[:60], 4)
        show("  unit_cost_gbp", pe.get("unit_cost_gbp"), 4)
    print()
    print("  ==> NOW OPEN THE 1310 WORKBOOK AND READ THESE CELLS:")
    print("        'Total Powder Per Unit'   (right of the Sheet Steel block)")
    print("        'Powder £/kg'             (AF82 — should be 9.73)")
    print("        the powder cost cell      (AF83)")
    print("      That is the number Dave is looking at. The JSON does not carry it.\n")


if __name__ == "__main__":
    main()
