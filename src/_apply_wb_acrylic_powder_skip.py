#!/usr/bin/env python3
r"""
_apply_wb_acrylic_powder_skip.py

THE REAL FIX for the phantom powder line on acrylic (12439). Earlier attempts patched
estimator.py / xlsx_output.py — the WRONG files. The powder BOM line is written in the LIVE
wb_populate.py, in the coated-area accumulation loop (~line 494) and the BOM write gate (~586).

WHY IT HAPPENS:
The loop that sums coated area accepts any part whose stock_form is "sheet", "plate", OR "" (empty):

    for _sp in _all_pes_pw:
        _sme = _sp.get("material_estimate") or {}
        if str(_sme.get("stock_form") or "").lower() not in ("sheet", "plate", ""):
            continue
        ...
        _sheet_powder_area_m2 += (_sl/1000)*(_sw/1000)*2.0*float(_sq)

An ACRYLIC part is a sheet form, so its area is summed as if it were coatable steel. That drives
_powder_kg_total > 0, and the gate at ~586 writes a "POWDER — computed from coated surface area"
BOM row. Acrylic is NEVER powder coated (it's diamond polished — the routing fix already handles
the operation side). So the acrylic area must NOT enter the coated-area sum.

FIX: skip acrylic/plastic parts in the accumulation loop — they contribute ZERO coated area.
Then, for a pure-acrylic job like 12439: _sheet_powder_area_m2 = 0; and the per-piece floor
must also NOT count acrylic pieces as coated, else the floor alone would re-introduce powder.
So the _fab_pieces / _coated_pieces count is also made to exclude acrylic. With no coated steel,
_powder_kg_total = 0, the write gate is skipped, and no powder row appears.

For a MIXED job (steel + acrylic): steel parts still contribute area and still get powder; only
the acrylic parts are excluded. Correct in both cases.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_wb_acrylic_powder_skip.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "acrylic_excluded_from_powder"

_ACR = '{"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"}'


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for (first 500 chars) ---\n{old[:500]}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# ── 1. the coated-area accumulation loop: skip acrylic parts ────────────────────────────
AREA_ANCHOR = '''    _sheet_powder_area_m2 = 0.0
    for _sp in _all_pes_pw:
        _sme = _sp.get("material_estimate") or {}
        if str(_sme.get("stock_form") or "").lower() not in ("sheet", "plate", ""):
            continue
        _sng = _sp.get("normalized_geometry") or {}'''

AREA_NEW = '''    _sheet_powder_area_m2 = 0.0
    # acrylic_excluded_from_powder (2026-07-15): acrylic / perspex / PMMA / polycarbonate are
    # diamond polished, NEVER powder coated. An acrylic part is a sheet form, so without this
    # guard its area was summed into the coated total and a phantom POWDER BOM row was written
    # (12439). Exclude acrylic/plastic from the coated-area sum. Steel parts are unaffected.
    _ACR_NO_POWDER = {"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"}
    def _is_acrylic_pw(_p):
        _m = str(_p.get("normalized_material")
                 or (_p.get("material_estimate") or {}).get("material") or "").upper().replace("_", " ")
        return _m in _ACR_NO_POWDER or bool(_p.get("acrylic_no_powder"))
    for _sp in _all_pes_pw:
        _sme = _sp.get("material_estimate") or {}
        if str(_sme.get("stock_form") or "").lower() not in ("sheet", "plate", ""):
            continue
        if _is_acrylic_pw(_sp):
            continue   # acrylic is not powder coated — contributes zero coated area
        _sng = _sp.get("normalized_geometry") or {}'''


# ── 2. the per-piece floor: don't count acrylic pieces as coated ────────────────────────
FLOOR_ANCHOR = '''    _fab_pieces = 0
    for _fp in _all_pes_pw:
        _fsf = str((_fp.get("material_estimate") or {}).get("stock_form") or "").lower()
        if _fsf in ("sheet", "plate", "wire", "bar", "board"):
            _fab_pieces += int(_safe(_fp.get("quantity"), 1) or 1)'''

FLOOR_NEW = '''    _fab_pieces = 0
    for _fp in _all_pes_pw:
        _fsf = str((_fp.get("material_estimate") or {}).get("stock_form") or "").lower()
        if _is_acrylic_pw(_fp):
            continue   # acrylic is not coated — must not count toward the per-piece powder floor
        if _fsf in ("sheet", "plate", "wire", "bar", "board"):
            _fab_pieces += int(_safe(_fp.get("quantity"), 1) or 1)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    src = sub(src, AREA_ANCHOR, AREA_NEW, "wb_populate: skip acrylic in coated-area loop")
    src = sub(src, FLOOR_ANCHOR, FLOOR_NEW, "wb_populate: skip acrylic in per-piece floor")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_wbacrylicpowder_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)
    print(f"  backup: {bak}")

    print("""
RE-RUN 12439 (qty 2025). Expected:
    - POWDER BOM line GONE (0.1153 m2 was the acrylic part's area; now excluded).
    - Material £0.84 -> ~£0.54 (still carries the oversized acrylic sheet £0.53).
    - Unit cost £3.16 -> ~£2.86.
    - Operations unchanged (Diamond Polish + Peel + Linebend + Assemble/pack).

REGRESSION: re-run 1282 (steel, real powder). Its POWDER line MUST remain and its unit cost
must be unchanged — this patch only excludes acrylic parts. If 1282's powder survives intact,
the guard cuts exactly where intended and nowhere else.
""")


if __name__ == "__main__":
    main()
