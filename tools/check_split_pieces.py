"""Prove a part split into its pieces through the record AND the charged workbook cells.

    python tools\\check_split_pieces.py output\\json\\<job>.json output\\<job>_<stamp>.xlsx <part code>

WHY (D-669/D-670 review, 4 Nov 2026). A split is not proven by tests or by a record that
lists pieces: it is proven where the money is. This reads the run's saved record and the
workbook Excel saved (open it once in Excel first if it was written without calculated
values) and checks, for the part named and every piece whose code is that part's plus a
number:

  pieces       one record per numbered flat, each at its own size; no extra piece
  parent       the part itself carries no material row of its own beside its pieces
  quantities   no piece is its own parent or child (no quantity cycle)
  holes        no hole inventory on the part or a piece that came from a drawing export
  bevels       which pieces were read as bevelled, and on what evidence
  set-ups      the labour rows naming the part or its pieces, and how many set-ups each
               department charges for them

Read-only. Generic: no job, code or figure is known here. Exit 1 when a check fails.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List


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


def _block_rows(ws, title: str) -> List[List[Any]]:
    """The rows under a block's caption (col C) up to the next blank description."""
    start = None
    for r in range(1, ws.max_row + 1):
        if str(ws.cell(r, 3).value or "").strip() == title:
            start = r + 2                               # caption, then the header row
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


def main() -> int:
    if len(sys.argv) < 4:
        print(__doc__)
        return 2
    record, book, code = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3].strip().upper()
    doc = json.loads(record.read_text(encoding="utf-8", errors="ignore"))
    recs = _records(doc, code)
    parent = recs.get(code) or {}
    pieces = {k: v for k, v in recs.items() if k != code}
    fails: List[str] = []

    print(f"== {code}: {len(pieces)} piece record(s) ==")
    for pn, p in sorted(pieces.items()):
        src = Path(str((p.get("dxf_orphan") or {}).get("path") or p.get("dxf_source_file") or "")).name
        bev = p.get("bevel_reading") or {}
        print(f"  {pn}: {_num(p.get('overall_length_mm')):g} x {_num(p.get('overall_width_mm')):g} "
              f"x {_num(p.get('normalized_thickness_mm')):g} mm, qty {p.get('quantity')}, "
              f"from {src or '(no flat)'}; bevel "
              + (f"TAKEN {bev.get('angle_deg'):g} deg on {bev.get('edges')} edge(s), "
                 f"{_num(bev.get('bevelled_edge_mm')):.0f} mm ({bev.get('because')})"
                 if bev.get("taken") else
                 ("not taken, question stands" if bev else "no inner lines")))
        if not src:
            fails.append(f"{pn} has no flat of its own: a piece nothing measured")
    if not pieces:
        fails.append(f"no piece records: {code} was not split into the pieces its flats number")
    sizes = [(round(_num(p.get("overall_length_mm"))), round(_num(p.get("overall_width_mm"))))
             for p in pieces.values()]
    if pieces and any(s == (0, 0) for s in sizes):
        fails.append("a piece has no size")

    print(f"== {code} itself ==")
    print(f"  assembly parent: {bool(parent.get('is_assembly_parent'))}; drawing views kept: "
          f"{[Path(str(v)).name for v in (parent.get('dxf_drawing_views') or [])]}")
    for pn, p in recs.items():
        kids = [str(k).upper() for k in (p.get("assembly_children") or [])]
        if pn in kids or str(p.get("bom_parent") or "").upper() == pn:
            fails.append(f"{pn} is its own parent or child: a quantity cycle")
        if p.get("hole_sizes_mm"):
            fails.append(f"{pn} carries a hole inventory {p.get('hole_sizes_mm')}: confirm it "
                         f"is not a drawing export's circles")

    try:
        import openpyxl
        ws = openpyxl.load_workbook(book, data_only=True)["Estimate"]
    except Exception as exc:                                          # noqa: BLE001
        print(f"!! workbook not read ({type(exc).__name__}: {exc})")
        return 1
    names = [code] + sorted(pieces)

    def _names_in(cell: Any) -> List[str]:
        text = str(cell or "").upper()
        return [n for n in names if re.search(rf"(?<![\w-]){re.escape(n)}(?![\w-]|-\d)", text)]

    print("== material rows (Other Sheet Material) ==")
    seen: Dict[str, int] = {}
    for row in _block_rows(ws, "Other Sheet Material"):
        r, desc, qty, L, W, T, SL, SW, per, scrap, sheet_gbp, part_gbp = row[:12]
        hit = _names_in(str(desc).split()[0] if desc else "")
        if not hit:
            continue
        seen[hit[0]] = seen.get(hit[0], 0) + 1
        print(f"  row {r}: {desc!s:.40} qty {qty} {L} x {W} x {T} on {SL} x {SW}, "
              f"{per}/sheet, £{_num(part_gbp):.2f}")
    if pieces and seen.get(code):
        fails.append(f"{code} has a material row of its own beside its pieces")
    for pn in pieces:
        if seen.get(pn, 0) != 1:
            fails.append(f"{pn} has {seen.get(pn, 0)} material row(s), not one")

    print("== labour rows naming the part or its pieces ==")
    setups: Dict[str, List[float]] = {}
    for row in _block_rows(ws, "Labour"):
        r, op, desc, _e, part_no, dept, qty, rate, hours, gbp_h, setup, value = row[:12]
        if not _names_in(part_no) and not _names_in(desc):
            continue
        setups.setdefault(str(op), []).append(_num(setup))
        print(f"  row {r}: {op} [{dept}] parts {part_no} qty {qty} rate {rate} "
              f"{_num(hours):.2f} h, set-up {setup} min, £{_num(value):.2f}")
    for op, mins in sorted(setups.items()):
        print(f"  {op}: {len(mins)} row(s), {sum(mins):g} set-up min in all")
        if len(mins) > 1 and op.startswith("CNC Joinery"):
            fails.append(f"{op}: {len(mins)} rows each with a set-up for one board's panels")

    print("== verdict ==")
    for f in fails:
        print(f"  FAIL  {f}")
    if not fails:
        print("  PASS  pieces, parent, quantities, holes and set-ups as checked above")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
