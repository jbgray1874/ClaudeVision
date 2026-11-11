"""Show how a part and its pieces were costed, from a saved or replayed record. Read-only.

    python tools/show_piece_costing.py output/replay/<job>_replay.json <part code>
    python tools/show_piece_costing.py output/json/<job>.json <part code>

WHY (D-679, 4 Nov 2026). A replay re-costs a saved record through the current code without a
twenty-minute run; this prints what the reviewer has to judge before a run is worth starting:
for each piece, its board money and how the board was built (core, facing, adhesive or the
named gap), whether its bevel was taken and from which sheet, the bevel minutes on its CNC
time, and the edging it shows; then every edging line, its code, metres and decor. The
workbook stays the proof of the charged cells; this says whether the path reached them.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


def _sq(v: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def _estimates(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    es = doc.get("estimate_summary") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for key in ("part_estimates", "canonical_part_estimates"):
        for pe in es.get(key) or []:
            if isinstance(pe, dict) and pe.get("part_number"):
                out.setdefault(_sq(pe["part_number"]), pe)
    return out


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("record", type=Path)
    ap.add_argument("code")
    a = ap.parse_args(argv)
    doc = json.loads(a.record.read_text(encoding="utf-8", errors="ignore"))
    code = a.code.strip().upper()
    recs = [p for p in ((doc.get("manufacturing_writeup") or {}).get("parts") or [])
            if isinstance(p, dict)]
    est = _estimates(doc)
    parent = next((p for p in recs if _sq(p.get("part_number")) == _sq(code)), {})
    pieces = sorted((p for p in recs if re.match(rf"^{re.escape(code)}-\d{{1,2}}$",
                                                 str(p.get("part_number") or "").upper())),
                    key=lambda p: str(p.get("part_number")))
    if doc.get("replay_of"):
        print(f"== replay of {doc.get('replay_of')} on build {doc.get('replay_build')}")
    print(f"== {code}: {len(pieces)} piece(s); decor "
          f"{parent.get('normalized_colour') or parent.get('colours') or '(none on record)'}")
    tot = parent.get("edging_on_its_pieces") or {}
    if tot:
        print(f"   edging its pieces show: {tot.get('mm')} mm; not measured "
              f"{tot.get('not_measured') or 'none'}")
    for p in pieces:
        pn = str(p.get("part_number"))
        pe = est.get(_sq(pn)) or {}
        me = pe.get("material_estimate") or {}
        print(f"\n-- {pn}: {p.get('overall_length_mm') or p.get('blank_length_mm')} x "
              f"{p.get('overall_width_mm') or p.get('blank_width_mm')} x "
              f"{p.get('normalized_thickness_mm')} mm, qty {p.get('quantity')}; decor "
              f"{p.get('normalized_colour') or p.get('colours') or '(none)'}"
              + (f" (from {p['product_reference_inherited_from']})"
                 if p.get("product_reference_inherited_from") else ""))
        print(f"   board: £{me.get('unit_material_cost_gbp')} a part, method "
              f"{me.get('cost_method')}, sheet £{me.get('sheet_price_gbp')}, flags "
              f"{me.get('reliability_flags')}")
        bc = me.get("board_construction") or {}
        if bc:
            print(f"   built: {bc.get('note')}")
            if not bc.get("adhesive_priced"):
                print(f"   adhesive gap: {bc.get('adhesive_gap')}")
        br = p.get("bevel_reading") or {}
        print(f"   bevel: " + (("TAKEN " if br.get("taken") else "not taken ")
                               + f"angles printed {br.get('angles_printed')}, from "
                                 f"{br.get('evidence_from')}" if br else "no reading"))
        bm = p.get("bevel_machining") or {}
        if bm:
            print(f"   bevel pass: {bm.get('length_mm')} mm, {bm.get('run_min')} min run + "
                  f"{bm.get('setup_min')} min set-up ({bm.get('basis')})")
        pr = pe.get("process_estimate") or {}
        print(f"   CNC: run {(pr.get('run_times_min_per_unit') or {}).get('cnc_routing')} min, "
              f"set-up {(pr.get('setup_times_min') or {}).get('cnc_routing')} min")
        ex = p.get("edging_on_exposed_edges") or {}
        if ex:
            print(f"   edging shows: {ex.get('mm')} mm of {ex.get('perimeter_mm')} mm outline")
    lines = [p for p in recs if p.get("_edging_line")] or \
        [pe for pe in est.values() if pe.get("_edging_line")]
    print(f"\n== edging line(s): {len(lines)}")
    shows = {str(p.get("part_number")): (p.get("edging_on_exposed_edges") or {}).get("mm")
             for p in pieces if (p.get("edging_on_exposed_edges") or {}).get("mm")}
    for ln in lines:
        print(f"   {ln.get('part_number')} x{ln.get('quantity')} m: {ln.get('description')}")
        row = ln.get("_edging_row") or {}
        if row:
            print(f"   SDI Live row: {row.get('part_code')} {row.get('width_mm')} x "
                  f"{row.get('thickness_mm')} mm, row price {row.get('row_gbp')}")
        print(f"   metres by piece: " + (", ".join(f"{k} {v:g} mm" for k, v in shows.items())
                                         or "none recorded")
              + f"; for {ln.get('_edging_for')}")
        print("   waste: none included; the metres are the edges themselves")
        lpe = est.get(_sq(ln.get("part_number"))) or {}
        lme = lpe.get("material_estimate") or {}
        print(f"   priced: £{lme.get('unit_material_cost_gbp')} a {ln.get('unit_of_measure')}, "
              f"method {lme.get('cost_method')}; source "
              f"{json.dumps(lme.get('price_source') or {}, default=str)[:300]}")
        for f in ln.get("review_flags") or []:
            if isinstance(f, str) and f.startswith("EDGING"):
                print(f"      {f[:220]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
