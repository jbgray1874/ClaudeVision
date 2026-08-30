#!/usr/bin/env python3
r"""
_apply_acrylic_powder_suppress.py

12439 (acrylic cube) still shows a POWDER BOM line at £0.30 after the routing fix. Acrylic is
NEVER powder coated - it's diamond polished (the routing fix already added Diamond Polish and
removed the powder OPERATION). But the powder CONSUMABLE (BOM material line) is built separately,
in the sheet-material estimator, and wasn't gated on material.

ROOT: estimator.py ~1396 builds powder_consumable for EVERY sheet part via
_powder_consumable_estimate(), regardless of material. xlsx_output.py then writes a POWDER BOM
row from it. An acrylic part gets a phantom powder line.

FIX (at source, so it's suppressed EVERYWHERE - BOM, rollups, totals - not just one write site):
gate the powder_consumable build on material. If the part is acrylic/plastic, powder_block = None.

This is the general rule: powder coat is a STEEL finish. Acrylic/perspex/PMMA/polycarbonate are
not powder coated. Same class of rule as the routing fix (acrylic finish = diamond polish).

Result on 12439: the POWDER £0.30 BOM line disappears; material drops £0.84 -> £0.54 (still
carries the oversized acrylic sheet £0.53, a separate issue).

Does NOT affect steel parts (powder still builds for them). Does NOT affect the bonded acrylic
tank's finish either - acrylic is diamond polished whether single part or assembly.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_powder_suppress.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "acrylic_powder_suppressed_v1"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


ANCHOR = '''    powder_block = _powder_consumable_estimate(part, blank_length, blank_width, quantity)
    powder_ext = float((powder_block or {}).get("extended_powder_material_cost_gbp") or 0.0)'''

NEW = '''    powder_block = _powder_consumable_estimate(part, blank_length, blank_width, quantity)
    # acrylic_powder_suppressed_v1 (2026-07-15): powder coat is a STEEL finish. Acrylic /
    # perspex / PMMA / polycarbonate are diamond polished, never powder coated. Suppress the
    # powder CONSUMABLE (BOM material line) at source for these materials, so no phantom POWDER
    # row reaches the workbook, rollups or totals. (The powder OPERATION is already gated out in
    # the acrylic routing block; this handles the material line.)
    _mat_pw = str(material or part.get("normalized_material") or "").upper().replace("_", " ")
    if _mat_pw in {"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"} \\
            or part.get("acrylic_no_powder"):
        powder_block = None
    powder_ext = float((powder_block or {}).get("extended_powder_material_cost_gbp") or 0.0)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    # sanity: 'material' must be in scope at this point (it's assigned earlier in the function)
    idx = src.find(ANCHOR)
    if idx == -1:
        sys.exit("ABORT: anchor not found. NOTHING WRITTEN.")
    preceding = src[max(0, idx-4000):idx]
    if "material = part.get(\"normalized_material\")" not in preceding and "material =" not in preceding:
        print("  WARN: could not confirm 'material' var in scope above anchor; the patch also")
        print("        falls back to part['normalized_material'] and the acrylic_no_powder flag,")
        print("        so it is safe regardless.")

    src = sub(src, ANCHOR, NEW, "estimator: suppress powder consumable for acrylic at source")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_acrylicpowder_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)
    print(f"  backup: {bak}")

    print("""
RE-RUN 12439 (qty 2025). Expected:
    - POWDER BOM line GONE. Material £0.84 -> ~£0.54.
    - Unit cost £3.16 -> ~£2.86.
    - Operations unchanged (Diamond Polish + Peel + Linebend + Assemble/pack).

Then the remaining acrylic gaps are just:
    - acrylic sheet 317x182 @ £46.20 -> £0.53 vs Tony 311x101 @ £0.12  (size + rate)
    - assemble/pack band 30/hr vs Tony 120  (needs acrylic pack size-banding)
    - linebend qty 2 vs 1  (bend over-read or Tony books per-part)

REGRESSION: re-run 1282 to confirm STEEL powder is untouched (it must still carry powder;
this patch only suppresses it for acrylic materials).
""")


if __name__ == "__main__":
    main()
