"""The AI Print calculator, read as estimating keeps it (JG, 13 Nov 2026).

SDI_PRINT_CALCULATOR_XLSX names the workbook. It holds one row per printed substrate (name,
print process, sheet size, set-up cost, run cost per sheet) and one working line that turns a
panel's length and width into parts per sheet and a cost per part.

This module reads the substrate table and works the sheet's own sums, cell for cell, so its
answer can be compared with Excel's. It is NOT yet a source of any charge on an estimate:
the sheet as it stands carries figures estimating has to confirm first, and each is reported
by `points_to_confirm` rather than corrected here:

  * scrap is entered as -0.7, which charges 30% of the sheet cost per part;
  * only one substrate carries a set-up cost;
  * the yield tries one orientation and trims the sheet's width but not its length;
  * the sheet sizes and costs are typed again inside the formulas.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

SOURCE = "AI Print calculator"
GUTTER_MM = 10.0            # the sheet adds 10 mm each side of a part: (part + 10*2)
WIDTH_TRIM_MM = 5.0         # and takes 5 mm off the sheet's width: (sheet width - 5)


def configured_path() -> Optional[str]:
    p = os.getenv("SDI_PRINT_CALCULATOR_XLSX", "").strip().strip('"')
    return p or None


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _sheet_size(text: Any) -> Optional[List[float]]:
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)", str(text or ""))
    return [float(m.group(1)), float(m.group(2))] if m else None


def read_sheet(path: Optional[str] = None) -> Dict[str, Any]:
    """{"ok", "path", "substrates", "scrap", "why"}. Never raises."""
    path = path or configured_path()
    out: Dict[str, Any] = {"ok": False, "path": path, "substrates": [], "scrap": None, "why": ""}
    if not path:
        out["why"] = "SDI_PRINT_CALCULATOR_XLSX is not set"
        return out
    if not Path(path).is_file():
        out["why"] = f"the print calculator is not at {path}"
        return out
    try:
        import openpyxl
        ws = openpyxl.load_workbook(path, data_only=False).worksheets[0]
    except Exception as exc:                                         # noqa: BLE001
        out["why"] = f"the print calculator could not be opened: {exc}"
        return out
    want = {"C1": "sheet size", "D1": "set-up cost", "A9": "material", "I9": "scrap %"}
    for cell, label in want.items():
        got = str(ws[cell].value or "").strip().lower()
        if got != label:
            out["why"] = (f"the print calculator's {cell} reads '{got or 'nothing'}', not "
                          f"'{label}': its layout has changed, so it is not used")
            return out
    for r in range(2, 9):
        name = str(ws.cell(r, 1).value or "").strip()
        run = _num(ws.cell(r, 5).value)
        size = _sheet_size(ws.cell(r, 3).value)
        if not name or run is None or not size:
            continue
        out["substrates"].append({
            "row": r, "name": name, "process": str(ws.cell(r, 2).value or "").strip(),
            "sheet_mm": size, "setup_gbp": _num(ws.cell(r, 4).value),
            "run_cost_per_sheet_gbp": run})
    out["scrap"] = _num(ws["I10"].value)
    if not out["substrates"]:
        out["why"] = "the print calculator holds no priced substrates"
        return out
    out["ok"] = True
    return out


def substrate(read: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    want = " ".join(str(name or "").split()).lower()
    for s in read.get("substrates") or []:
        if " ".join(s["name"].split()).lower() == want:
            return s
    return None


def parts_per_sheet(length_mm: float, width_mm: float, sheet_mm: List[float]) -> int:
    """The sheet's own yield (H10): one orientation, a 10 mm gutter each side of the part,
    5 mm off the sheet's width and nothing off its length. 0 when the part does not fit."""
    sheet_l, sheet_w = float(sheet_mm[0]), float(sheet_mm[1])
    if length_mm <= 0 or width_mm <= 0 or length_mm > sheet_l or width_mm > sheet_w:
        return 0
    across = int((sheet_w - WIDTH_TRIM_MM) / (width_mm + 2 * GUTTER_MM))
    along = int(sheet_l / (length_mm + 2 * GUTTER_MM))
    return max(0, across) * max(0, along)


def as_the_sheet_works_it(read: Dict[str, Any], name: str, length_mm: float, width_mm: float,
                          quantity: float, panels: float = 1.0) -> Dict[str, Any]:
    """The sheet's TOTAL for one part (I2), worked as the sheet works it and shown in steps.
    {"ok": False, "why": ...} when it cannot be worked. Not a charge: see the module note."""
    out: Dict[str, Any] = {"ok": False, "source": SOURCE, "applied": False, "why": ""}
    if not read.get("ok"):
        out["why"] = read.get("why") or "the print calculator was not read"
        return out
    s = substrate(read, name)
    if s is None:
        out["why"] = f"'{name}' is not a substrate on the print calculator"
        return out
    per_sheet = parts_per_sheet(length_mm, width_mm, s["sheet_mm"])
    if per_sheet <= 0:
        out["why"] = (f"a {length_mm:g} x {width_mm:g} mm part does not fit a "
                      f"{s['sheet_mm'][0]:g} x {s['sheet_mm'][1]:g} mm sheet as the sheet lays it")
        return out
    if not quantity or quantity <= 0:
        out["why"] = "no quantity to spread the set-up over"
        return out
    scrap = read.get("scrap") or 0.0
    cost_per_part = (s["run_cost_per_sheet_gbp"] / per_sheet) * (1.0 + scrap) * panels   # K10
    first = (read.get("substrates") or [{}])[0]
    setup = first.get("setup_gbp") or 0.0                                               # D2 only
    total = setup / quantity + cost_per_part                                            # I2
    out.update(ok=True, substrate=s["name"], parts_per_sheet=per_sheet, scrap=scrap,
               cost_per_part_gbp=round(cost_per_part, 4), setup_gbp=setup,
               setup_share_gbp=round(setup / quantity, 4), total_gbp=round(total, 4),
               points_to_confirm=points_to_confirm(read))
    return out


def points_to_confirm(read: Dict[str, Any]) -> List[str]:
    """What estimating has to confirm on the sheet before it prices anything."""
    said: List[str] = []
    scrap = read.get("scrap")
    if scrap is not None and scrap < 0:
        said.append(f"Scrap is entered as {scrap:g}: the cost per part is the sheet cost per "
                    f"part times {1 + scrap:.0%}, a reduction, not an allowance.")
    subs = read.get("substrates") or []
    without = [s["name"] for s in subs if not s.get("setup_gbp")]
    if subs and without and len(without) < len(subs):
        said.append(f"Only {len(subs) - len(without)} of {len(subs)} substrates carries a set-up "
                    f"cost; the total always uses the first row's.")
    if subs:
        said.append("The yield tries one orientation only, and trims 5 mm from the sheet's "
                    "width and nothing from its length.")
    return said
