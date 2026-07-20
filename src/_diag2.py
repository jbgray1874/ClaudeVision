import json, glob, os, re
f = max(glob.glob(r"C:\ClaudeVision\output\json\*Milwaukee*.json"), key=os.path.getmtime)
d = json.load(open(f, encoding="utf-8"))
parts = d.get("manufacturing_writeup", {}).get("parts") or []

print("=== LOOM (expect ONE line, BI-50CMLOOM, with a Reconciled flag) ===")
for p in parts:
    if "LOOM" in str(p.get("description","")).upper() or p.get("part_number") in ("BI-50CMLOOM","ELECTRICS 50CM"):
        rec = [x for x in (p.get("review_flags") or []) if "Reconciled" in str(x)]
        print(" ", repr(p.get("part_number")), "| roles=", p.get("page_roles"), "| reconciled_flag=", bool(rec))

print("\n=== x2 CASCADE: effective qty each part ends up costed at ===")
# show the qty that actually reaches costing per part (whatever field the estimate carries)
for p in parts:
    pn = p.get("part_number")
    if pn in ("1448-01","1448-02","3886-01","3886-02","3886-03","1449-01C","2621-01C","1450-01C"):
        q = p.get("quantity")
        eq = p.get("effective_quantity") or p.get("qty_per_unit") or p.get("resolved_quantity")
        print(f'  {pn:<12} quantity={q}  effective/resolved={eq}  parent={p.get("parent_part") or p.get("bom_parent")}')
