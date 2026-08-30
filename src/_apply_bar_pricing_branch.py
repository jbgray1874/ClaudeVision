#!/usr/bin/env python3
r"""
_apply_bar_pricing_branch.py

WHERE THE LAST PATCH STOPPED
----------------------------
document_builder now recognises the bar correctly — the probe proved it:

    _bar_recognised: True   wire_gauge_mm: 8.0   wire_length_mm: 65.0
    stock_form: 'wire'      thickness: None (diameter correctly cleared)
    operations: robomac, welding, handling
    per-part gate held: 1310-01 (pages=[3]) untouched, still steel

But estimator.py never priced it as wire, so it kept falling into the BOM — and got WORSE
(£6.69 -> £25.77), because clearing normalized_thickness_mm made _safe_thickness_mm(part)
return None and the sheet path priced it at some fallback thickness.

WHY IT NEVER PRICED AS WIRE — the same spelling test, a second time (estimator.py:1505):

    is_wire = any(kw in desc_upper for kw in ("WIRE MESH", "WELDED WIRE", "WIRE FORM",
                                              "WIREWORK", "WIRE "))
    if is_wire and length_mm:

The part's description is "STUD". The word "wire" appears nowhere. Exactly the same
spelling-based gate we just fixed in document_builder — it exists twice.

Two further traps sat behind it:
  * gauge_mm = _safe_thickness_mm(part) or 3.0   -> now returns 3.0 (we cleared thickness),
    so even reaching the branch would price an 8mm bar as 3mm wire.
  * the whole block is gated by _is_section_or_wire_candidate(), which we have not read.

THE FIX
-------
Insert a SELF-CONTAINED bar branch BEFORE the section/wire block. It fires only when
document_builder set _bar_recognised, uses the gauge and length already on the part, and
touches none of the existing wire/tube/section logic.

THE NUMBER IS DERIVED, NOT INVENTED — two independent routes agree:

  WB gauge table (row 223):  8mm -> 2534 m/tonne
  From first principles:     area = pi*(8/2000)^2 = 5.027e-5 m2
                             kg/m = x 7850        = 0.3946
                             m/tonne = 1000/0.3946 = 2534.3   <- the same 2534

  price/m = £1600 / 2534.3            = £0.6313
  unit    = 0.6313/1000 x 65 x 1.04   = £0.0427

  Tim's manual sheet:                   £0.04

Same formula the WB uses (cost_method "workbook_wire_formula"), same £1600/tonne, same 4%
scrap. wb_populate then writes gauge+length into the Wire block and the WB recomputes it
itself — no double count, because the wire block only receives desc/qty/gauge/length.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_bar_pricing_branch.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "workbook_bar_formula"

ANCHOR = (
    "    # Section/tube/wire path: uses linear stock mass estimate when profile+length is available.\n"
    "    if _is_section_or_wire_candidate(part, material):"
)

NEW = '''    # ── ROUND BAR / STUD path (added 2026-07-13) ─────────────────────────────
    # Fires ONLY when document_builder recognised a bar schedule on the part's own page:
    #       ITEM  QTY  DESCRIPTION  LENGTH
    #         1    1    8mm DIA      65
    #
    # This has to be its own branch. The wire path below keys on the WORD "wire" in the
    # description (WIRE MESH / WELDED WIRE / WIRE FORM / ...) — the same spelling test we
    # just removed from document_builder, present here a second time. A solid bar whose
    # drawing says "STUD" can never satisfy it. And gauge_mm there falls back to 3.0 when
    # thickness is absent, which would price an 8mm bar as 3mm wire.
    #
    # Uses the SAME formula and rates as the workbook, so the engine's JSON total and the
    # WB's own Wire block agree:
    #     8mm -> 2534 m/tonne (WB gauge table; also = 1000 / (pi*(d/2000)^2 * 7850))
    #     price/m = £1600 / 2534 = £0.6313
    #     unit    = 0.6313/1000 x 65mm x 1.04 = £0.0427     (Tim's sheet: £0.04)
    if part.get("_bar_recognised"):
        _bar_gauge = _safe_float(part.get("wire_gauge_mm"))
        _bar_len = _safe_float(part.get("wire_length_mm"))
        if _bar_gauge and _bar_len:
            wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
            _wire_per_tonne = float(wb_defaults.get("wire_cost_per_tonne_gbp") or 1600.0)
            _gauge_table = getattr(config, "WIRE_GAUGE_TABLE", {}) or {}
            _m_per_tonne = None
            if _gauge_table:
                _closest = min(_gauge_table.keys(), key=lambda g: abs(float(g) - _bar_gauge))
                # only trust the table if it actually has this gauge (within 0.25mm)
                if abs(float(_closest) - _bar_gauge) <= 0.25:
                    _m_per_tonne = float(_gauge_table[_closest])
            if not _m_per_tonne:
                # derive from the solid round section — matches the WB table exactly
                _area_m2 = 3.14159265 * ((_bar_gauge / 2000.0) ** 2)
                _kg_per_m = _area_m2 * 7850.0
                _m_per_tonne = (1000.0 / _kg_per_m) if _kg_per_m > 0 else None
            if _m_per_tonne and _m_per_tonne > 0:
                _price_per_m = _wire_per_tonne / _m_per_tonne
                _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
                _unit = (_price_per_m / 1000.0) * _bar_len * (1.0 + _scrap)
                _ext = _unit * quantity
                return {
                    "material": material,
                    "thickness_mm": None,          # a DIAMETER is not a thickness
                    "blank_length_mm": _bar_len,
                    "blank_width_mm": None,
                    "blank_area_m2": None,
                    "unit_material_mass_kg": round(_bar_len / 1000.0 / _m_per_tonne * 1000.0, 5),
                    "unit_material_cost_gbp": round(_unit, 4),
                    "cost_per_part_gbp": round(_unit, 4),
                    "extended_material_cost_gbp": round(_ext, 2),
                    "stock_estimate": {
                        "wire_length_mm": _bar_len,
                        "wire_gauge_mm": _bar_gauge,
                        "metres_per_tonne": round(_m_per_tonne, 1),
                        "price_per_metre_gbp": round(_price_per_m, 6),
                    },
                    "cost_method": "workbook_bar_formula",
                    "stock_form": "wire",
                    "wire_gauge_mm": _bar_gauge,
                    "wire_length_mm": _bar_len,
                    "requires_flat_blank": False,
                    "part_confidence_overall": _part_confidence_overall(part),
                    "part_geometry_reliability": _part_geometry_reliability(part),
                    "price_source": _build_price_source_metadata(
                        external_result, fallback_source="config_wire_cost_per_tonne",
                        applied=True, applied_basis="bar_diameter_x_length_gauge_lookup",
                    ),
                }

''' + ANCHOR


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")

    src = open(TARGET, "r", encoding="utf-8").read()

    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    n = src.count(ANCHOR)
    if n != 1:
        sys.exit(f"ABORT: anchor found {n} times, expected 1. Nothing written.\n"
                 f"--- looked for ---\n{ANCHOR}\n")

    src = src.replace(ANCHOR, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_barprice_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  inserted round-bar pricing branch before the section/wire path")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 1310 (qty 50):

    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="50"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\1310 Drill Stud Holder (Rev C)" --folder-as-job

EXPECT (Tim's manual in brackets):
    * console: "1 wire/bar"
    * 1310-02 STUD *OUT* of the BOM entirely
    * WIRE block row: gauge 8, length 65, qty 1   -> ~£0.04     (Tim £0.04)
    * Robomac labour row                          -> ~£0.17     (Tim £0.17)
    * HOOK PLATE still in the STEEL block
    * unit cost drops hard from £31.93 (Tim £6.90; P.Coat £2.00 + Weld £1.25 still missing,
      so expect roughly £4.30-£4.60 — UNDER Tim, and that is the honest position until the
      powder-pointer and weld defects are fixed)

THEN regress 1282 (qty 10) — it has NO bars, so it MUST be unchanged at £278.93.
Any movement means the bar branch is firing where it should not: revert immediately.
""")


if __name__ == "__main__":
    main()
