#!/usr/bin/env python3
r"""
_apply_wire_powder_scope_fix.py

WHY IT DID NOT FIRE

The field names were right — me.get("wire_gauge_mm") / me.get("wire_length_mm"), exactly as
the wire-block writer uses at wb_populate.py:536. The wire block successfully wrote gauge 4
and length 975.4 to the sheet, so those values are certainly there.

The problem is SCOPE. I inserted the area calculation immediately before the BOM block
(~line 435). The wire block is at ~line 498. If wire_parts is built BETWEEN those two points,
my loop iterated an empty list, produced 0.0, and the powder line fell through to the
"withheld" branch without a word.

I guessed the insertion point instead of checking. That is the third time tonight I have
assumed where a value lives rather than reading it — the finish (normalized_finish vs
surface_finishes), the RAW check, and now this.

THE FIX: REMOVE THE DEPENDENCY

Read the parts from `summary` and filter on stock_form. `summary` is in scope everywhere and
does not care what order the blocks are written in. No ordering assumption left to get wrong.

AND MAKE IT SELF-DIAGNOSING

If the area still computes to zero, say so — with the part list and what each one carried.
A silent zero is how this hid in the first place.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_wire_powder_scope_fix.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_wire_powder_diag"

OLD = '''    _wire_powder_area_m2 = 0.0
    for _wp in wire_parts:
        _wme = _wp.get("material_estimate") or {}
        _wg = _safe(_wme.get("wire_gauge_mm") or _wp.get("wire_gauge_mm"))
        _wl = _safe(_wme.get("wire_length_mm") or _wp.get("wire_length_mm"))
        _wq = _safe(_wp.get("quantity"), 1) or 1
        if _wg and _wl:
            _wire_powder_area_m2 += 3.14159265 * (_wg / 1000.0) * (_wl / 1000.0) * float(_wq)
    _wire_powder_kg = round(_wire_powder_area_m2 * float(_POWDER_KG_PER_M2), 5)'''

NEW = '''    # Read from `summary`, NOT from wire_parts. The previous version looped wire_parts from
    # a point in the file where it may not have been built yet — it silently iterated an
    # empty list, produced 0.0, and the powder line fell through to "withheld" without a
    # word. `summary` is in scope everywhere and carries no ordering assumption.
    _wire_powder_area_m2 = 0.0
    _wire_powder_diag = []
    _all_pes_pw = ((summary.get("estimate_summary") or {}).get("part_estimates")
                   or summary.get("parts") or [])
    for _wp in _all_pes_pw:
        _wme = _wp.get("material_estimate") or {}
        if str(_wme.get("stock_form") or "").lower() not in ("wire", "bar"):
            continue
        _wg = _safe(_wme.get("wire_gauge_mm") or _wp.get("wire_gauge_mm"))
        _wl = _safe(_wme.get("wire_length_mm") or _wp.get("wire_length_mm"))
        _wq = _safe(_wp.get("quantity"), 1) or 1
        _wire_powder_diag.append(f"{_wp.get('part_number')}(g={_wg},l={_wl},q={_wq})")
        if _wg and _wl:
            # A wire is a CYLINDER — its whole surface is coated, so area = pi * d * L.
            # (No x2: that is a flat sheet, which has two faces.)
            _wire_powder_area_m2 += 3.14159265 * (_wg / 1000.0) * (_wl / 1000.0) * float(_wq)
    _wire_powder_kg = round(_wire_powder_area_m2 * float(_POWDER_KG_PER_M2), 5)
    if _wire_powder_diag and _wire_powder_kg <= 0:
        # Never fail silently again. If we found wire parts but no area, say what they held.
        _flag(f"powder: found {len(_wire_powder_diag)} wire/bar part(s) but computed ZERO "
              f"coated area — {'; '.join(_wire_powder_diag)}. Powder NOT costed on the wire. "
              f"Gauge/length missing from the pricing record.", flags)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")
    if "_wire_powder_area_m2" not in src:
        sys.exit("Run _apply_wire_powder_area.py first — its block is the anchor.")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match, found {n}. Nothing written.")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_wirepowderscope_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  wire powder area now read from `summary` — no ordering assumption")
    print("  ok  self-diagnosing: a zero area with wire parts present now says so")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 7670 (qty 50), then 1310 and 1282.

EXPECT ON 7670:
    * flag: "POWDER computed from WIRE geometry: 0.02346 m2 ... 0.00391 kg @ £7.72/kg"
    * BOM powder row PRICED: 0.00391 kg @ £7.72  ->  ~£0.03    (Tim £0.40)
    * unit cost £7.58 -> ~£7.62

IF IT STILL DOES NOT FIRE, the console now prints every wire part and the gauge/length it
carried. No fourth guess.

    £0.03 vs Tim's £0.40 is THE COVERAGE RATE, not the geometry. The area is right. The
    template's 0.1667 kg/m2 is 100% transfer efficiency and is wrong on EVERY job — 1310
    shipped at £0.06 against Tim's £0.30 this morning. config.POWDER_KG_PER_M2 = 1.70 would
    land 7670 exactly on Tim, but that fits ONE data point. Measure it: powder_rule_v2.sql q5.

REGRESSIONS — neither has a powder BOM line:
    1310  £9.07     1282  £207.16
""")


if __name__ == "__main__":
    main()
