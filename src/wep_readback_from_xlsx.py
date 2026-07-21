r"""
wep_readback_from_xlsx.py — make the JSON's price match the SPREADSHEET's price.

ROOT PROBLEM (diagnosed session 25): the summary JSON's
`estimate_summary.workbook_equivalent_pricing` (m59/m103/m105) is a Python RECONSTRUCTION of the
unit cost. It has DRIFTED from what the estimators' Excel template actually computes: the JSON
said £214.11 while the populated .xlsx computes £189.01. Every consumer that reads the JSON block
(parity report, pricing_service, pricing_variance, fallback writer) therefore shows the wrong,
stale price. wb_populate itself is correct — it writes Excel formulas and Excel computes the real
total on load.

FIX (Path 2, general, any job): after wb_populate saves the .xlsx, open it via Excel COM, force a
full calculation, read the three AUTHORITATIVE computed totals by label-scan (Total Material Cost,
Total Labour Cost, Total Unit Cost Price), and write them back into the JSON's
workbook_equivalent_pricing + cost_breakdown. The JSON then MATCHES the spreadsheet, so every
consumer is consistent.

STRICTLY ADDITIVE & FAILURE-ISOLATED: if Excel COM is unavailable or anything fails, the JSON is
left unchanged (old WEP retained) and a warning is logged. A populate run NEVER fails on this.

Public API:
    stamp_real_totals_into_json(xlsx_path, json_path, sheet_name="Estimate") -> dict|None
        Returns {"material":.., "labour":.., "unit":.., "source":"excel_com"} on success,
        or None if it couldn't read (JSON untouched).

Standalone:
    python wep_readback_from_xlsx.py --xlsx <populated.xlsx> --json <summary.json>
"""
from __future__ import annotations
import argparse, json, sys, re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ---- Excel COM open + full calc (mirrors estimate_full_parity_report._open_workbook_excel_com) ----
def _open_xlsx_excel_com(path: Path, prime_sheet: Optional[str] = None):
    if sys.platform != "win32":
        raise RuntimeError("Excel COM readback is only supported on Windows.")
    import win32com.client  # type: ignore
    p = str(path.resolve())
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.ScreenUpdating = False
    try:
        excel.EnableEvents = False
    except Exception:
        pass
    try:
        com_wb = excel.Workbooks.Open(p, 0, True)   # UpdateLinks=0, ReadOnly=True
    except Exception:
        try:
            excel.Quit()
        except Exception:
            pass
        raise
    try:
        try:
            excel.Calculation = -4105               # xlCalculationAutomatic
        except Exception:
            pass
        try:
            com_wb.ForceFullCalculation = True
        except Exception:
            pass
        if prime_sheet:
            try:
                com_wb.Worksheets(prime_sheet).Activate()
            except Exception:
                pass
        try:
            excel.CalculateFull()
        except Exception:
            try:
                excel.Calculate()
            except Exception:
                pass
        try:
            excel.CalculateUntilAsyncQueriesDone()
        except Exception:
            pass
    except Exception:
        pass
    return excel, com_wb


def _close_excel(excel, com_wb) -> None:
    try:
        com_wb.Close(SaveChanges=False)
    except Exception:
        pass
    try:
        excel.Quit()
    except Exception:
        pass


# ---- label-scan on the calculated sheet (find 'Total Material/Labour/Unit' -> value to the right) ----
_TOTAL_LABELS = {
    "material": ("total material cost",),
    "labour": ("total labour cost",),          # matches 'Total Labour Cost (Including Downtime)'
    "unit": ("total unit cost",),               # 'Total Unit Cost Price'
}


def _scan_total(com_ws, label_needles: Tuple[str, ...], max_row: int, max_col: int) -> Optional[float]:
    """Find a row whose text contains one of the needles, return the rightmost numeric on that row."""
    for r in range(1, max_row + 1):
        row_has_label = False
        for c in range(1, min(max_col, 16) + 1):
            try:
                v = com_ws.Cells(r, c).Value
            except Exception:
                v = None
            if isinstance(v, str):
                low = v.lower()
                if any(n in low for n in label_needles):
                    row_has_label = True
                    break
        if not row_has_label:
            continue
        # rightmost numeric on this row = the computed subtotal
        best = None
        for c in range(1, max_col + 1):
            try:
                v = com_ws.Cells(r, c).Value
            except Exception:
                v = None
            f = _safe_float(v)
            if f is not None and f != 0:
                best = f
        if best is not None:
            return best
    return None


def _used_bounds(com_ws) -> Tuple[int, int]:
    try:
        ur = com_ws.UsedRange
        return int(ur.Rows.Count) + 5, int(ur.Columns.Count) + 2
    except Exception:
        return 240, 34


def read_real_totals(xlsx_path: Path, sheet_name: str = "Estimate") -> Optional[Dict[str, float]]:
    """Open the populated .xlsx via Excel COM, calc, read the three authoritative totals."""
    excel = com_wb = None
    try:
        excel, com_wb = _open_xlsx_excel_com(xlsx_path, prime_sheet=sheet_name)
        try:
            com_ws = com_wb.Worksheets(sheet_name)
        except Exception:
            com_ws = com_wb.ActiveSheet
        max_row, max_col = _used_bounds(com_ws)
        out: Dict[str, float] = {}
        for key, needles in _TOTAL_LABELS.items():
            val = _scan_total(com_ws, needles, max_row, max_col)
            if val is not None:
                out[key] = round(val, 4)
        return out or None
    except Exception as exc:
        print(f"   [wep-readback] Excel COM read failed ({type(exc).__name__}: {exc}) — JSON left unchanged.", flush=True)
        return None
    finally:
        if excel is not None:
            _close_excel(excel, com_wb)


# ---- write the real totals into the JSON's WEP + cost_breakdown ----
def stamp_real_totals_into_json(xlsx_path: str, json_path: str, sheet_name: str = "Estimate") -> Optional[Dict[str, Any]]:
    xp, jp = Path(xlsx_path), Path(json_path)
    if not xp.exists():
        print(f"   [wep-readback] xlsx not found: {xp} — skipped.", flush=True)
        return None
    if not jp.exists():
        print(f"   [wep-readback] json not found: {jp} — skipped.", flush=True)
        return None

    totals = read_real_totals(xp, sheet_name=sheet_name)
    if not totals or "unit" not in totals:
        print("   [wep-readback] could not read authoritative unit cost — JSON left unchanged (old WEP retained).", flush=True)
        return None

    material = totals.get("material")
    labour = totals.get("labour")
    unit = totals.get("unit")

    try:
        summary = json.loads(jp.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"   [wep-readback] JSON read failed ({exc}) — skipped.", flush=True)
        return None

    es = summary.get("estimate_summary")
    if not isinstance(es, dict):
        print("   [wep-readback] JSON has no estimate_summary — skipped.", flush=True)
        return None

    wep = es.get("workbook_equivalent_pricing")
    if not isinstance(wep, dict):
        wep = {}
        es["workbook_equivalent_pricing"] = wep

    # record what we changed for the audit trail
    before = {k: wep.get(k) for k in ("m59_material_subtotal_gbp", "m103_labour_subtotal_gbp",
                                      "m105_total_unit_cost_gbp", "l105_total_unit_cost_gbp")}

    if material is not None:
        wep["m59_material_subtotal_gbp"] = round(material, 4)
    if labour is not None:
        wep["m103_labour_subtotal_gbp"] = round(labour, 4)
    if unit is not None:
        wep["m105_total_unit_cost_gbp"] = round(unit, 4)
        wep["l105_total_unit_cost_gbp"] = round(unit, 4)
    # provenance: these are now READ FROM the calculated workbook, not reconstructed
    wep.setdefault("assumptions", {})
    if isinstance(wep.get("assumptions"), dict):
        wep["assumptions"]["unit_cost_source"] = "excel_com_readback"
        wep["assumptions"]["reconstruction_superseded"] = True
    wep["source_of_truth"] = "populated_xlsx_excel_com"

    # keep cost_breakdown in step
    cb = es.get("cost_breakdown")
    if isinstance(cb, dict):
        if isinstance(cb.get("material"), dict) and material is not None:
            cb["material"]["total"] = round(material, 4)
        if isinstance(cb.get("labour"), dict) and labour is not None:
            cb["labour"]["total"] = round(labour, 4)

    try:
        jp.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        print(f"   [wep-readback] JSON write failed ({exc}) — JSON left unchanged.", flush=True)
        return None

    print(f"   [wep-readback] stamped real totals into JSON: material £{material}, labour £{labour}, unit £{unit} "
          f"(was unit £{before.get('m105_total_unit_cost_gbp')}).", flush=True)
    return {"material": material, "labour": labour, "unit": unit,
            "source": "excel_com", "before": before}


def main() -> None:
    ap = argparse.ArgumentParser(description="Stamp Excel-computed totals from a populated .xlsx into the summary JSON's workbook_equivalent_pricing.")
    ap.add_argument("--xlsx", required=True, help="Populated estimate .xlsx")
    ap.add_argument("--json", required=True, help="Summary JSON to update")
    ap.add_argument("--sheet", default="Estimate", help="Estimate sheet name (default: Estimate)")
    a = ap.parse_args()
    res = stamp_real_totals_into_json(a.xlsx, a.json, sheet_name=a.sheet)
    if res:
        print(f"OK: {res}")
    else:
        print("No change (see message above).")


if __name__ == "__main__":
    main()
