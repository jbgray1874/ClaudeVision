"""The AI Tube calculator, read as estimating keeps it (JG, 13 Nov 2026).

"wire in the two new calculators" ... "ai tube calculator".

The workbook is estimating's own: one row per tube stock (SDI Live part code, description,
cost of one stock length, and what a cut, a hole, a slot and a mitre cost on that stock).
SDI_TUBE_CALCULATOR_XLSX names it, as SDI_BOX_CALCULATOR_XLSX names the box calculator.
Unset or unreadable, the engine prices tube exactly as before and says nothing changed.

What is wired: the stock rows join the engine's tube and section price rows, under their own
part codes, named as coming from this calculator. A code the calculator prices takes the
calculator's price, because the sheet is where estimating changes it.

What is NOT wired: the cut, hole, slot and mitre rates. They are read and returned so a run
can record them, and they replace nothing until estimating says they should replace the
engine's own tube-laser times (open decision, 13 Nov 2026).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SOURCE = "AI Tube calculator"
HEADERS = {"A": "part", "D": "material cost", "E": "cut cost", "F": "cost per hole",
           "G": "cost per slot", "H": "cost per mitre"}


def configured_path() -> Optional[str]:
    p = os.getenv("SDI_TUBE_CALCULATOR_XLSX", "").strip().strip('"')
    return p or None


_STATED_LENGTH = re.compile(r"\(\s*(\d+(?:\.\d+)?)\s*(m|mtr|metre|metres)\s*\)", re.I)


def stated_stock_length_m(description: Any) -> Optional[float]:
    """The stock length a row's own description states, in metres: "(6.1m)" gives 6.1.
    None when it states none or more than one. The length is read from each row and never
    assumed (reviewer, 13 Nov 2026: "Do not assume every tube stock row is 6.1 m")."""
    found = {round(float(v), 3) for v, _u in _STATED_LENGTH.findall(str(description or ""))}
    return found.pop() if len(found) == 1 else None


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def read_sheet(path: Optional[str] = None) -> Dict[str, Any]:
    """{"ok", "path", "rows", "why"}. Never raises; a sheet laid out differently is refused
    with the reason, never half-read."""
    path = path or configured_path()
    out: Dict[str, Any] = {"ok": False, "path": path, "rows": [], "why": ""}
    if not path:
        out["why"] = "SDI_TUBE_CALCULATOR_XLSX is not set"
        return out
    if not Path(path).is_file():
        out["why"] = f"the tube calculator is not at {path}"
        return out
    try:
        import openpyxl
        ws = openpyxl.load_workbook(path, data_only=True, read_only=True).worksheets[0]
        grid = [list(r) for r in ws.iter_rows(min_row=1, max_col=8, values_only=True)]
    except Exception as exc:                                         # noqa: BLE001
        out["why"] = f"the tube calculator could not be opened: {exc}"
        return out
    if not grid:
        out["why"] = "the tube calculator's first sheet is empty"
        return out
    head = [str(c or "").strip().lower() for c in grid[0]] + [""] * 8
    for col, want in HEADERS.items():
        got = head[ord(col) - ord("A")]
        if got != want:
            out["why"] = (f"the tube calculator's column {col} is headed '{got or 'nothing'}', "
                          f"not '{want}': its layout has changed, so it is not used")
            return out
    for n, r in enumerate(grid[1:], start=2):
        r = list(r) + [None] * 8
        code = str(r[0] or "").strip().upper()
        cost = _num(r[3])
        if not code or cost is None or cost <= 0:
            continue
        _desc = str(r[2] or r[1] or "").strip()
        _len = stated_stock_length_m(_desc) or stated_stock_length_m(r[1])
        out["rows"].append({
            "row": n, "code": code,
            "stock_length_m": _len,
            "unit": (f"one {_len:g} m stock length" if _len else "NOT STATED on the row"),
            "description": str(r[2] or r[1] or "").strip(),
            "stock_length_cost_gbp": round(cost, 4),
            "cut_gbp": _num(r[4]), "hole_gbp": _num(r[5]),
            "slot_gbp": _num(r[6]), "mitre_gbp": _num(r[7]),
        })
    if not out["rows"]:
        out["why"] = "the tube calculator holds no priced stock rows"
        return out
    out["ok"] = True
    return out


def catalogue_rows(read: Optional[Dict[str, Any]] = None) -> List[Tuple[str, str, float, str, str]]:
    """The stock rows in the shape the engine's section price rows take:
    (part code, description, cost, supplier, unit). The unit is one stock length, as the
    sheet's own descriptions say ("(6.1m)")."""
    read = read if read is not None else read_sheet()
    if not read.get("ok"):
        return []
    # ONLY A ROW THAT STATES ITS OWN STOCK LENGTH PRICES ANYTHING. A cost with no stated unit
    # is not known to be a price per length, so it replaces no catalogue price.
    return [(r["code"], r["description"], r["stock_length_cost_gbp"], SOURCE, "EA")
            for r in read["rows"] if r.get("stock_length_m")]


def rows_without_a_stated_length(read: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """The priced rows whose description states no single stock length: the exceptions to
    put to estimating. They price nothing until the row says what its cost is for."""
    read = read if read is not None else read_sheet()
    return [{"row": r["row"], "code": r["code"], "description": r["description"],
             "stock_length_cost_gbp": r["stock_length_cost_gbp"]}
            for r in (read.get("rows") or []) if not r.get("stock_length_m")]


def merged_with(existing: Optional[List[Any]], read: Optional[Dict[str, Any]] = None
                ) -> Tuple[Optional[List[Any]], Dict[str, Any]]:
    """(rows to price from, what the calculator changed). A code the calculator prices takes
    the calculator's row; every other catalogue row is kept as it was."""
    read = read if read is not None else read_sheet()
    said: Dict[str, Any] = {"source": SOURCE, "used": False, "path": read.get("path"),
                            "why_not": read.get("why") or "", "replaced": [], "added": []}
    mine = catalogue_rows(read)
    if not mine:
        return existing, said
    codes = {m[0] for m in mine}
    kept = [r for r in (existing or []) if str(r[0] or "").strip().upper() not in codes]
    had = {str(r[0] or "").strip().upper() for r in (existing or [])}
    _lengths = sorted({r["stock_length_m"] for r in read["rows"] if r.get("stock_length_m")})
    said.update(used=True, why_not="",
                replaced=sorted(codes & had), added=sorted(codes - had), rows=len(mine),
                stock_lengths_m=_lengths,
                not_used_no_stated_length=[x["code"] for x in rows_without_a_stated_length(read)])
    return kept + mine, said


def rates_for(code: str, read: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The sheet's cut, hole, slot and mitre figures for one stock code, for the record.
    Not applied to any charge (see the module note)."""
    read = read if read is not None else read_sheet()
    want = str(code or "").strip().upper()
    for r in read.get("rows") or []:
        if r["code"] == want:
            return {k: r[k] for k in ("cut_gbp", "hole_gbp", "slot_gbp", "mitre_gbp")} | {
                "code": want, "source": SOURCE, "applied": False}
    return None
