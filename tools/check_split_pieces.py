"""Prove a part split into its pieces through the record AND the charged workbook cells.

    python tools\\check_split_pieces.py <record.json> <workbook.xlsx> <part code>
        [--sizes "375x177.1,375x177.1,270x177.1,270x99.1,375x270"] [--qty "1,1,1,1,1"]
        [--handed "1+2"]

WHY (D-669..D-671 reviews, 4 Nov 2026). A split is proven where the money is, and a workbook
that is structurally right can still be an incomplete estimate. So the verdict has two halves:

  STRUCTURE     one piece per numbered flat, at the size and quantity given (in piece-number
                order), handed pieces mirror images of each other, no material row for the
                part itself, no quantity cycle, no holes from a drawing export, and every
                shared set-up carrying the evidence that justifies it: a proven nest of the
                same machining shares ONE allowance; an unproven one keeps one per row.
  COMPLETENESS  every piece's board priced, every piece cut by a charged row, every bevel's
                machining priced, called-out edging charged as labour AND material.

The sizes, quantities and hands are the drawing's, given on the command line from the
estimator's own take-off; nothing about any job is held here. Read-only. Open the workbook
once in Excel first if it was written without calculated values. Exit 0 only when both halves
pass; a check that could not run is NOT VERIFIED, never a pass.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_CUTTING_ROWS = ("CNC Joinery", "Laser", "Saw", "Guillotine", "Waterjet", "CNC")
_BEVEL_ROWS = re.compile(r"BEVEL|MITRE|MITER|CHAMFER", re.I)


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _records(doc: Dict[str, Any], code: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in ((doc.get("manufacturing_writeup") or {}).get("parts") or []):
        pn = str((p or {}).get("part_number") or "").upper()
        if pn == code or re.match(rf"^{re.escape(code)}-\d{{1,2}}$", pn):
            out[pn] = p
    return out


def _labour_record(doc: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    node = doc.get("workbook_labour")
    if not isinstance(node, dict):
        node = (doc.get("estimate_summary") or {}).get("workbook_labour") or {}
    return {int(r["workbook_row"]): r for r in (node.get("rows") or [])
            if isinstance(r, dict) and r.get("workbook_row")}


def _block_rows(ws, title: str) -> List[List[Any]]:
    start = None
    for r in range(1, ws.max_row + 1):
        if str(ws.cell(r, 3).value or "").strip() == title:
            start = r + 2
            break
    rows: List[List[Any]] = []
    if start is None:
        return rows
    for r in range(start, ws.max_row + 1):
        c = ws.cell(r, 3).value
        if c in (None, "") or str(c).startswith("Total"):
            break
        rows.append([r] + [ws.cell(r, k).value for k in range(3, 14)])
    return rows


def _outline(path: Path):
    """The flat's outline polygon, moved to the origin; None when it cannot be read."""
    try:
        import bevel_reading as br
        from shapely.affinity import translate
        from shapely.geometry import LineString
        from shapely.ops import polygonize, unary_union
        got = br._segments(path)
        if not got:
            return None
        poly = unary_union(list(polygonize(unary_union(
            [LineString([a, b]) for a, b, _l in got[0] if a != b]))))
        if poly.is_empty:
            return None
        if poly.geom_type != "Polygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        minx, miny, _x, _y = poly.bounds
        return translate(poly, -minx, -miny)
    except Exception:                                                 # noqa: BLE001
        return None


def _hand(a, b) -> str:
    """"mirror", "identical" or "different" for two outlines."""
    from shapely.affinity import scale, translate
    def same(p, q):
        return p.symmetric_difference(q).area <= 0.01 * max(p.area, q.area)
    if same(a, b):
        return "identical"
    m = scale(a, xfact=-1, origin=(0, 0))
    minx, miny, _x, _y = m.bounds
    m = translate(m, -minx, -miny)
    if same(m, b):
        return "mirror"
    m2 = scale(a, yfact=-1, origin=(0, 0))
    minx, miny, _x, _y = m2.bounds
    return "mirror" if same(translate(m2, -minx, -miny), b) else "different"


def _flat(p: Dict[str, Any]) -> Optional[Path]:
    for c in ((p.get("dxf_orphan") or {}).get("path"), p.get("dxf_source_file")):
        if c and Path(str(c)).is_file():
            return Path(str(c))
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("record", type=Path)
    ap.add_argument("workbook", type=Path)
    ap.add_argument("code")
    ap.add_argument("--sizes", default="", help="LxW per piece, in piece-number order")
    ap.add_argument("--qty", default="", help="quantity per unit per piece, same order")
    ap.add_argument("--handed", default="", help='mirrored pairs by piece number, e.g. "1+2"')
    a = ap.parse_args()
    code = a.code.strip().upper()
    doc = json.loads(a.record.read_text(encoding="utf-8", errors="ignore"))
    recs = _records(doc, code)
    parent = recs.get(code) or {}
    pieces = {k: v for k, v in sorted(recs.items()) if k != code}
    struct: List[Tuple[str, str]] = []          # (PASS|FAIL|NOT VERIFIED, sentence)
    complete: List[Tuple[str, str]] = []

    def num_of(pn: str) -> int:
        return int(pn.rsplit("-", 1)[1])

    # ── STRUCTURE: the pieces ──
    print(f"== {code}: {len(pieces)} piece record(s) ==")
    for pn, p in pieces.items():
        bev = p.get("bevel_reading") or {}
        print(f"  {pn}: {_num(p.get('overall_length_mm')):g} x {_num(p.get('overall_width_mm')):g}"
              f" x {_num(p.get('normalized_thickness_mm')):g} mm, qty {p.get('quantity')}, flat "
              f"{(_flat(p) or Path('(not on this machine)')).name}; bevel "
              + (f"TAKEN {bev.get('angle_deg'):g} deg, {bev.get('edges')} edge(s), "
                 f"{_num(bev.get('bevelled_edge_mm')):.0f} mm, from {bev.get('evidence_from')}"
                 if bev.get("taken") else
                 (f"not taken ({bev.get('evidence_from')})" if bev else "no inner lines")))
    if not pieces:
        struct.append(("FAIL", f"no piece records: {code} was not split"))
    want = [s for s in a.sizes.split(",") if s.strip()]
    if want:
        if len(want) != len(pieces):
            struct.append(("FAIL", f"{len(pieces)} pieces against {len(want)} on the drawing"))
        for i, s in enumerate(want, start=1):
            L, W = sorted((float(x) for x in s.lower().split("x")), reverse=True)
            pn = f"{code}-{i:02d}"
            p = pieces.get(pn)
            if not p:
                struct.append(("FAIL", f"piece {i} ({s}) has no record"))
                continue
            got = sorted((_num(p.get("overall_length_mm")), _num(p.get("overall_width_mm"))),
                         reverse=True)
            ok = abs(got[0] - L) <= 1.0 and abs(got[1] - W) <= 1.0
            struct.append(("PASS" if ok else "FAIL",
                           f"{pn} is {got[0]:g} x {got[1]:g} against the drawing's {L:g} x {W:g}"))
    else:
        struct.append(("NOT VERIFIED", "no --sizes given: piece sizes not held to the drawing"))
    wq = [q for q in a.qty.split(",") if q.strip()]
    for i, q in enumerate(wq, start=1):
        p = pieces.get(f"{code}-{i:02d}") or {}
        ok = abs(_num(p.get("quantity")) - float(q)) < 1e-6
        struct.append(("PASS" if ok else "FAIL",
                       f"{code}-{i:02d} quantity {p.get('quantity')} against {q}"))
    for pair in [x for x in a.handed.split(",") if x.strip()]:
        i, j = (int(x) for x in pair.split("+"))
        fa, fb = _flat(pieces.get(f"{code}-{i:02d}") or {}), _flat(pieces.get(f"{code}-{j:02d}") or {})
        oa, ob = (_outline(fa) if fa else None), (_outline(fb) if fb else None)
        if oa is None or ob is None:
            struct.append(("NOT VERIFIED", f"pieces {i} and {j}: flats not readable here"))
        else:
            h = _hand(oa, ob)
            struct.append(("PASS" if h == "mirror" else "FAIL",
                           f"pieces {i} and {j} are {h} outlines (a handed pair mirrors)"))
    for pn, p in recs.items():
        kids = [str(k).upper() for k in (p.get("assembly_children") or [])]
        if pn in kids or str(p.get("bom_parent") or "").upper() == pn:
            struct.append(("FAIL", f"{pn} is its own parent or child: a quantity cycle"))
        if p.get("hole_sizes_mm") and parent.get("dxf_drawing_views"):
            struct.append(("FAIL", f"{pn} carries holes {p.get('hole_sizes_mm')} beside a "
                                   f"drawing export: confirm they are not its circles"))
    print(f"  {code}: assembly parent {bool(parent.get('is_assembly_parent'))}; drawing views "
          f"kept {[Path(str(v)).name for v in (parent.get('dxf_drawing_views') or [])]}")

    try:
        import openpyxl
        ws = openpyxl.load_workbook(a.workbook, data_only=True)["Estimate"]
    except Exception as exc:                                          # noqa: BLE001
        print(f"!! workbook not read ({type(exc).__name__}: {exc})")
        return 1
    names = [code] + list(pieces)

    def named(cell: Any) -> List[str]:
        text = str(cell or "").upper()
        return [n for n in names if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-]|-\d)", text)]

    # ── material rows ──
    print("== material rows (Other Sheet Material) ==")
    mat: Dict[str, List[List[Any]]] = {}
    edging_material = False
    for row in _block_rows(ws, "Other Sheet Material") + _block_rows(ws, "Bill of Materials"):
        desc = str(row[1] or "")
        if re.search(r"\bEDG", desc, re.I):
            edging_material = True
        hit = named(desc.split()[0] if desc.split() else "")
        if hit:
            mat.setdefault(hit[0], []).append(row)
            print(f"  row {row[0]}: {desc:.40} qty {row[2]} {row[3]} x {row[4]} x {row[5]}, "
                  f"{row[8]}/sheet, £{_num(row[11]):.2f} a part")
    if pieces and mat.get(code):
        struct.append(("FAIL", f"{code} has a material row of its own beside its pieces"))
    if not pieces:
        complete.append(("NOT VERIFIED", "no pieces to check: completeness cannot be judged"))
    for row in mat.get(code) or []:
        if _num(row[11]) <= 0:
            complete.append(("FAIL", f"{code}'s own material row has no price"))
    for pn, p in pieces.items():
        rows = mat.get(pn) or []
        if len(rows) != 1:
            struct.append(("FAIL", f"{pn} has {len(rows)} material row(s), not one"))
            continue
        if _num(rows[0][2]) != _num(p.get("quantity")):
            struct.append(("FAIL", f"{pn}'s material row carries qty {rows[0][2]} against the "
                                   f"record's {p.get('quantity')}"))
        if _num(rows[0][11]) <= 0:
            complete.append(("FAIL", f"{pn} has no board price: material cost incomplete"))

    # ── labour rows and their set-ups ──
    print("== labour rows naming the part or its pieces ==")
    lrec = _labour_record(doc)
    nests: Dict[str, List[Tuple[List[Any], Dict[str, Any]]]] = {}
    cut: set = set()
    bevel_priced: set = set()
    edging_rows: List[List[Any]] = []
    for row in _block_rows(ws, "Labour"):
        r, op, desc, _e, part_no, dept, qty, rate, hours, _gbp_h, setup, value = row[:12]
        hit = named(part_no) or named(desc)
        if not hit:
            continue
        rr = lrec.get(int(r)) or {}
        print(f"  row {r}: {op} [{dept}] {part_no} qty {qty} rate {rate} {_num(hours):.2f} h, "
              f"set-up {setup} min, £{_num(value):.2f}"
              + (f"\n      nest {rr.get('laser_nest_id')}: "
                 f"{'PROVEN' if rr.get('laser_nest_proven') else 'unproven'}, "
                 f"{rr.get('laser_nest_evidence')}" if rr.get("laser_nest_id") else ""))
        if any(str(op).startswith(c) for c in _CUTTING_ROWS):
            cut.update(hit)
            if rr.get("laser_nest_id"):
                nests.setdefault(str(rr["laser_nest_id"]), []).append((row, rr))
            elif str(op).startswith("CNC Joinery"):
                struct.append(("FAIL", f"row {r}: {op} carries no nest record, so its set-up "
                                       f"cannot be justified"))
        if _BEVEL_ROWS.search(str(op)) or _BEVEL_ROWS.search(str(desc)):
            bevel_priced.update(hit)
        if str(op).startswith("Edge Banding"):
            edging_rows.append(row)
    for nid, members in sorted(nests.items()):
        setups = [_num(m[0][10]) for m in members]
        proven = all(m[1].get("laser_nest_proven") for m in members)
        shared = all(m[1].get("setup_share") for m in members)
        if len(members) == 1:
            struct.append(("PASS", f"nest {nid}: one row, its own set-up "
                                   f"({members[0][1].get('laser_nest_evidence')})"))
        elif proven and shared and max(setups) - min(setups) < 1e-6:
            struct.append(("PASS", f"nest {nid}: {len(members)} rows share ONE set-up "
                                   f"({sum(setups):g} min in all), justified by: "
                                   f"{members[0][1].get('laser_nest_evidence')}"))
        elif proven:
            struct.append(("FAIL", f"nest {nid}: proven but the set-up is not allocated as one "
                                   f"({setups} min)"))
        elif shared:
            struct.append(("FAIL", f"nest {nid}: unproven yet its set-up was divided"))
        else:
            struct.append(("PASS", f"nest {nid}: unproven, so each of {len(members)} rows keeps "
                                   f"its own set-up ({members[0][1].get('laser_nest_evidence')});"
                                   f" overstated unless one program is confirmed"))

    # ── completeness: machining and edging ──
    for pn, p in pieces.items():
        if pn not in cut:
            complete.append(("FAIL", f"{pn} is cut by no charged row"))
        if (p.get("bevelled_edges") or {}).get("angle_deg") and pn not in bevel_priced:
            be = p["bevelled_edges"]
            complete.append(("FAIL", f"{pn}: {be.get('length_mm')} mm of {be.get('angle_deg'):g} "
                                     f"degree bevel recorded, its machining not priced"))
        if any(isinstance(q, dict) and q.get("subject") == "nested_outline_frame_or_step"
               for q in (p.get("manufacturing_questions") or [])):
            complete.append(("FAIL", f"{pn}: an inner feature is still a question"))
    edged = [pn for pn, p in recs.items() if "edge_banding" in (p.get("textual_operations") or [])]
    if edged:
        if not edging_rows:
            complete.append(("FAIL", f"edging read on {', '.join(edged)} has no labour row"))
        flags = " ".join(str(f) for pn in edged for f in (recs[pn].get("review_flags") or []))
        if "MINIMUM RUN" in flags or "TIMED ON THE PERIMETER" in flags:
            complete.append(("FAIL", "edging length not proven: timed at the minimum run or on "
                                     "a perimeter ceiling"))
        if not edging_material:
            complete.append(("FAIL", "edging is called out and no edging material is charged"))

    print("== STRUCTURE ==")
    for k, t in struct:
        print(f"  {k:<12} {t}")
    print("== COMPLETENESS ==")
    for k, t in complete or [("PASS", "nothing found missing")]:
        print(f"  {k:<12} {t}")
    s_ok = not any(k != "PASS" for k, _t in struct)
    c_ok = not any(k != "PASS" for k, _t in complete)
    print(f"== VERDICT: structure {'PASS' if s_ok else 'NOT PROVEN'}; estimate "
          f"{'COMPLETE' if c_ok else 'INCOMPLETE'} ==")
    return 0 if (s_ok and c_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
