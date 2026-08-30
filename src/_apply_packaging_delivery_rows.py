"""Applies the PACKAGING/DELIVERY-as-BOM-rows change to wb_populate.py.

Change: instead of DROPPING the PACKAGING and DELIVERY commercial placeholders,
route them into bom_parts so they write as £0 (blank-price) BOM rows for the
estimator to fill in — saving manual typing. Price stays blank/£0 (order-level
cost, not derivable from the drawing). The BOM writer already handles no-price
items (writes blank price + 'no price' flag), and the labour block only picks up
tube parts from bom_parts, so these get NO spurious labour line.

Exact string replace: either matches and applies, or refuses and changes nothing.
Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_packaging_delivery_rows.py
Then re-run 1298 AND 1282 and confirm each gains exactly one PACKAGING + one
DELIVERY £0 row, with nothing else changed.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")

OLD = '''        # 1. drop commercial placeholders
        if pn in DROP_CODES:
            continue'''

NEW = '''        # 1. commercial placeholders (PACKAGING / DELIVERY): write as blank-price
        #    (£0) BOM rows for the estimator to fill in, rather than dropping.
        #    Saves manual typing. Price is left blank on purpose — delivery/packaging
        #    cost is order-level (pallets, haulage share) and NOT derivable from the
        #    drawing, so the engine must not invent it; the BOM writer flags "no price".
        #    (Reverses the earlier "estimator adds manually" DROP, per estimator request.)
        if pn in DROP_CODES:
            bom_parts.append(pe)
            continue'''

src = TARGET.read_text(encoding="utf-8")

if "PACKAGING / DELIVERY): write as blank-price" in src:
    print("ALREADY APPLIED — the packaging/delivery-as-BOM-rows change is present.")
    print("Skip the applier; just re-run 1298 + 1282 and verify the rows.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED — exact text not found in wb_populate.py.")
    print("The live block differs from what I expect. Paste back:")
    print(r'  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "drop commercial placeholders" -Context 1,3')
    raise SystemExit(1)

if src.count(OLD) > 1:
    print(f"NOT APPLIED — found {src.count(OLD)} matches, expected 1. Refusing to guess.")
    raise SystemExit(1)

TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")
print("APPLIED — PACKAGING/DELIVERY now route to bom_parts as blank-price rows.")
print("Fingerprint: Select-String wb_populate.py -Pattern 'write as blank-price'")
print("Next: re-run 1298 AND 1282; confirm each gains 1 PACKAGING + 1 DELIVERY £0 row.")
