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


# Excel COM returns an errored cell (#VALUE!, #REF!, #DIV/0! …) as one of these int sentinels
# (the CVErr codes). A total that ERRORED — e.g. a material formula referencing a missing
# dimension cell (L=None) — must NEVER be cast to a float and stamped into the JSON as a real
# price. On the M&S Horti Crate run this leaked #VALUE! (-2146826273) back as "material £-2.1bn".
_EXCEL_ERROR_SENTINELS = frozenset({
    -2146826288,  # xlErrNull   #NULL!
    -2146826281,  # xlErrDiv0   #DIV/0!
    -2146826273,  # xlErrValue  #VALUE!
    -2146826265,  # xlErrRef    #REF!
    -2146826259,  # xlErrName   #NAME?
    -2146826252,  # xlErrNum    #NUM!
    -2146826246,  # xlErrNA     #N/A
})

# No costing subtotal on this template is ever this large in magnitude; anything beyond it is
# either an error sentinel that slipped through or a corrupt read — reject rather than stamp.
_IMPLAUSIBLE_TOTAL = 1e8


def _is_excel_error(v: Any) -> bool:
    """True if a COM cell value is an Excel error sentinel (errored formula), not a real number."""
    return isinstance(v, int) and not isinstance(v, bool) and v in _EXCEL_ERROR_SENTINELS


def _safe_float(v: Any) -> Optional[float]:
    if _is_excel_error(v):
        return None
    try:
        if v is None or v == "":
            return None
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or abs(f) >= _IMPLAUSIBLE_TOTAL:  # NaN or absurd magnitude -> not a credible total
        return None
    return f


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


# ── the FINAL rows, as Excel calculated them ────────────────────────────────────────
# wb_populate can only record what it PUT IN — quantities, throughputs, the department it
# chose. Hours, rates, costs and values are Excel formulas that do not evaluate until the
# file is opened, so a snapshot taken at write time carries none of them. Anything
# describing the finished estimate from that snapshot is describing the input, not the
# result. These are read AFTER calculation, from the sheet itself.
#
# Columns are located by HEADER TEXT, not by index: the estimators' template shifts rows and
# columns when the BOM block grows, and a hardcoded column would go quietly stale rather
# than fail. Same reasoning as _find_wb_sell_price_ref scanning for its label.
_LABOUR_HEADER_KEYS = {
    "operation": "operation", "part description": "description", "dept": "department",
    # Named for what they CONTAIN, not what the template's headers say. On this sheet
    # "Rate Per Hour" is a THROUGHPUT (99 pieces/hour) and "Labour Cost" is the department's
    # HOURLY RATE (GBP 25.43/hr) - only "Total Value" is a per-unit cost. Carrying the header
    # wording into a JSON contract would hand an ERP integration two fields whose names say
    # the opposite of their contents.
    "qty per unit": "qty_per_unit", "rate per hour": "throughput_per_hour",
    "total hours": "batch_hours", "labour cost": "dept_rate_gbp_per_hour",
    "set up": "setup_minutes", "total value": "total_value_gbp",
}
_MATERIAL_HEADER_KEYS = {
    "bill of materials": "description", "part code": "part_code", "supplier": "supplier",
    "price": "unit_price_gbp", "qty per unit": "qty_per_unit", "scrap": "scrap_pct",
    "total value": "total_value_gbp",
}
# The fabricated blocks are NOT the BOM and do not share its columns. Each names its value
# column differently — "Cost" on tube, "Cost Per Part" on steel and other-sheet — so mapping
# them all through the BOM's "Total Value" returned rows carrying no value, which is why the
# material rows could not sum to the sheet's own Total Material Cost.
_TUBE_HEADER_KEYS = {
    "part description": "description", "qty per unit": "qty_per_unit", "gauge": "gauge",
    "length": "length_mm", "price per m": "price_per_m_gbp", "kgs": "mass_kg",
    "scrap": "scrap_pct", "cost": "total_value_gbp",
}
_SHEET_HEADER_KEYS = {
    "part description": "description", "qty per unit": "qty_per_unit",
    "part length": "length_mm", "part width": "width_mm", "gauge": "gauge",
    "thickness": "thickness_mm", "qty per sheet": "qty_per_sheet", "scrap": "scrap_pct",
    "cost per part": "total_value_gbp",
}


def _header_map(com_ws, header_row: int, keys: Dict[str, str],
                max_col: int) -> Dict[str, int]:
    """{normalised field name: column index} by matching header text on one row."""
    found: Dict[str, int] = {}
    for c in range(1, max_col + 1):
        try:
            v = com_ws.Cells(header_row, c).Value
        except Exception:
            continue
        if not isinstance(v, str):
            continue
        t = " ".join(v.split()).strip().lower()
        if not t:
            continue
        for needle, field in keys.items():
            if field not in found and needle in t:
                found[field] = c
                break
    return found


def _find_header_row(com_ws, first_data_row: int, needles: Tuple[str, ...],
                     max_col: int) -> Optional[int]:
    """The header row for a block: search upward from its first data row."""
    for r in range(max(1, first_data_row - 6), first_data_row + 1):
        row_text = ""
        for c in range(1, min(max_col, 24) + 1):
            try:
                v = com_ws.Cells(r, c).Value
            except Exception:
                continue
            if isinstance(v, str):
                row_text += " " + v.lower()
        if all(n in row_text for n in needles):
            return r
    return None


def _read_block(com_ws, first_row: int, last_row: int, keys: Dict[str, str],
                needles: Tuple[str, ...], id_field: str, max_col: int,
                block_name: str = "", problems: Optional[list] = None,
                value_field: str = "total_value_gbp") -> list:
    """Rows of one workbook block, as calculated. Blank identity = end of the used rows;
    an Excel error is carried through as None rather than a number, because a cell showing
    #DIV/0! is missing data and must not be read as zero.

    A BLOCK THAT CANNOT BE READ SAYS SO. Returning [] for a missing header is indistinguish-
    able from a block that is genuinely empty, and the two mean opposite things: one is "no
    tube on this job", the other is "the template moved and we are now under-reporting the
    material total". That silence is what let the fabricated blocks go missing from the
    read-back — nothing failed, the rows were simply absent, and the total was quietly 43p
    short. Every unreadable block is appended to `problems` for the caller to surface.
    """
    def _problem(code: str, message: str, **detail) -> list:
        if problems is not None:
            problems.append({"block": block_name or "?", "code": code,
                             "message": message, "detail": detail})
        return []

    hr = _find_header_row(com_ws, first_row, needles, max_col)
    if hr is None:
        return _problem(
            "header_row_not_found",
            f"No header row for the '{block_name}' block above row {first_row} carrying "
            f"{list(needles)}. The template layout has moved or the block was renamed; its "
            f"rows are NOT in this read-back and any total built from it is short.",
            searched_above_row=first_row, needles=list(needles))
    cols = _header_map(com_ws, hr, keys, max_col)
    if id_field not in cols:
        return _problem(
            "identity_column_not_found",
            f"The '{block_name}' block header at row {hr} has no column matching "
            f"'{id_field}', so its rows cannot be identified and were not read.",
            header_row=hr, mapped=sorted(cols))
    if value_field and value_field not in cols:
        # Rows without their value column read back as identity-only and silently contribute
        # nothing to the total — exactly the tube/steel/other-sheet defect.
        _problem("value_column_not_found",
                 f"The '{block_name}' block header at row {hr} has no value column "
                 f"(expected one matching {[k for k, v in keys.items() if v == value_field]}). "
                 f"Its rows carry no cost and will not reconcile to the sheet total.",
                 header_row=hr, mapped=sorted(cols))
    out = []
    for r in range(first_row, last_row + 1):
        try:
            ident = com_ws.Cells(r, cols[id_field]).Value
        except Exception:
            continue
        if ident is None or not str(ident).strip():
            continue
        row: Dict[str, Any] = {"workbook_row": r}
        for field, c in cols.items():
            try:
                v = com_ws.Cells(r, c).Value
            except Exception:
                v = None
            if _is_excel_error(v):
                row[field] = None
            elif isinstance(v, str):
                row[field] = " ".join(v.split()).strip()
            else:
                row[field] = _safe_float(v) if isinstance(v, (int, float)) else v
        out.append(row)
    return out


def read_final_rows(com_ws, max_col: int) -> Dict[str, list]:
    """The Estimate sheet's calculated labour and BOM rows.

    Block bounds come from wb_populate's own CELL_MAP so the two cannot disagree about
    where the blocks are; falls back to the known defaults if that import is unavailable."""
    bom_first, bom_last, lab_first, lab_last = 11, 50, 96, 167
    try:
        from wb_populate import CELL_MAP as _CM
        bom_first = int(_CM["bom"]["first_row"]); bom_last = int(_CM["bom"]["last_row"])
        lab_first = int(_CM["labour"]["first_row"]); lab_last = int(_CM["labour"]["last_row"])
    except Exception:
        pass
    # EVERY material block, not just the bought-in BOM. Reading rows 11-50 alone omitted the
    # wire, sheet-steel and other-sheet blocks, so the snapshot's material rows could not sum
    # to the sheet's Total Material Cost - on 12120 it was GBP 9.64 of a GBP 10.07 total,
    # with the missing 43p being exactly the fabricated material. A snapshot that does not
    # reconcile to its own total is not a snapshot anyone can build an ERP export on.
    # Block names come from CELL_MAP itself. Asking for "wire" when the map defines "tube"
    # skipped the block silently — nothing failed, the rows were simply absent.
    _blocks = [("bom", bom_first, bom_last, ("bill of materials", "total value"),
                _MATERIAL_HEADER_KEYS)]
    _missing_blocks = []
    try:
        from wb_populate import CELL_MAP as _CM2
        for _name, _needles, _keys in (
                ("tube", ("gauge", "price per m"), _TUBE_HEADER_KEYS),
                ("steel", ("part length", "cost per part"), _SHEET_HEADER_KEYS),
                ("other_sheet", ("thickness", "cost per part"), _SHEET_HEADER_KEYS)):
            _b = _CM2.get(_name)
            if _b:
                _blocks.append((_name, int(_b["first_row"]), int(_b["last_row"]),
                                _needles, _keys))
            else:
                # A block this adapter expects but the template no longer defines. Silence
                # here is what made the tube block vanish from the read-back.
                _missing_blocks.append(_name)
    except Exception as _exc:
        _missing_blocks.append(f"CELL_MAP unavailable ({_exc}) — only the BOM was read")

    problems: list = [{"block": b, "code": "block_not_in_cell_map",
                       "message": f"CELL_MAP defines no '{b}' block, so nothing was read from "
                                  f"it and the material total may be short.", "detail": {}}
                      for b in _missing_blocks]

    mats = []
    for _name, _f, _l, _needles, _keys in _blocks:
        for _r in _read_block(com_ws, _f, _l, _keys, _needles, "description", max_col,
                              block_name=_name, problems=problems):
            _r["block"] = _name
            mats.append(_r)

    return {
        "labour_rows": _read_block(com_ws, lab_first, lab_last, _LABOUR_HEADER_KEYS,
                                   ("operation", "total hours"), "operation", max_col,
                                   block_name="labour", problems=problems),
        "material_rows": mats,
        # Surfaced, not swallowed. The caller stamps these onto the job so an invariant can
        # fail on them instead of a total quietly coming up short.
        "adapter_problems": problems,
    }


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
        out: Dict[str, Any] = {}
        for key, needles in _TOTAL_LABELS.items():
            val = _scan_total(com_ws, needles, max_row, max_col)
            if val is not None:
                out[key] = round(val, 4)
        # Same COM session, same calculated state: opening Excel twice would be slow and
        # could read a differently-calculated file. Failure here must not lose the totals.
        try:
            out["_final_rows"] = read_final_rows(com_ws, max_col)
        except Exception as _rexc:
            print(f"   [wep-readback] calculated rows not read ({_rexc}) — totals kept.",
                  flush=True)
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
    _final_rows = totals.pop("_final_rows", None) or {}

    try:
        summary = json.loads(jp.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"   [wep-readback] JSON read failed ({exc}) — skipped.", flush=True)
        return None

    es = summary.get("estimate_summary")
    if not isinstance(es, dict):
        print("   [wep-readback] JSON has no estimate_summary — skipped.", flush=True)
        return None

    # ── final_estimate.v1 — the one post-Excel contract ──────────────────────────────
    # Totals AND rows, read from the same calculated sheet. Everything downstream (sheets,
    # HTML, comparison CSV, ERP export) should describe the estimate from this and nothing
    # else: it is the only structure that reflects what the workbook actually computed,
    # rather than what was handed to it. wb_populate's workbook_labour remains as the
    # accepted INPUT grouping — useful for provenance, but it has no hours, rates or values
    # and must not be mistaken for the result.
    if _final_rows.get("labour_rows") or _final_rows.get("material_rows"):
        summary["final_estimate"] = {
            "schema": "final_estimate.v2",
            "source": "excel_calculated",
            "note": ("Rows as the Estimate sheet calculated them. Authoritative for what the "
                     "job contains and what each line costs. Excel errors are carried as "
                     "null, never as zero — a cell showing #DIV/0! is missing data."),
            "totals": {"material_gbp": material, "labour_gbp": labour, "unit_gbp": unit},
            "labour_rows": _final_rows.get("labour_rows") or [],
            "material_rows": _final_rows.get("material_rows") or [],
            # Blocks this adapter could not read. Present and empty means "we checked".
            "adapter_problems": _final_rows.get("adapter_problems") or [],
        }
        for _p in (_final_rows.get("adapter_problems") or []):
            print(f"   [wep-readback] BLOCK NOT READ — {_p.get('message')}", flush=True)
        print(f"   [wep-readback] final_estimate.v2 stamped — "
              f"{len(_final_rows.get('labour_rows') or [])} calculated labour row(s), "
              f"{len(_final_rows.get('material_rows') or [])} BOM row(s)", flush=True)

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
