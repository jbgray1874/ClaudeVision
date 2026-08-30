"""READ-ONLY. Resolve the puzzle: does 1282 REALLY have 0 hole ops and 0 deferred
finishes, or did the previous probe just look under the wrong keys?

1282 visibly HAS holes (1449 = 386 pierces) and 'SEE ASSEMBLY DRAWING' finishes
(1448-01, 3886-02/03 in the console). So a literal 0 is suspicious. This dumps the
RAW finish + operation fields for every 1282 part under EVERY plausible key, so we
can't be fooled by a field-name mismatch.

If the data is really there (just under other keys) -> the fixes MIGHT touch 1282 -> NOT safe.
If 1282 genuinely has no hole ops / resolved finishes -> fixes are safe AND 1282 shows the correct mechanism.
"""
import io, json
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json")
d = json.load(io.open(J, encoding="utf-8"))

# gather parts from every plausible container
containers = []
mw = d.get("manufacturing_writeup") or {}
if mw.get("parts"): containers.append(("manufacturing_writeup.parts", mw["parts"]))
if d.get("parts"): containers.append(("parts", d["parts"]))
es = d.get("estimate_summary") or {}
for k in ("parts","part_estimates"):
    if es.get(k): containers.append((f"estimate_summary.{k}", es[k]))

print("Containers found:", [c[0] for c in containers])

# for each part, dump finish-ish and operation-ish fields under all likely keys
FINISH_KEYS = ["finishes","finish","normalized_finish","normalised_finish","surface_finish","finish_detected"]
OP_KEYS     = ["operations","textual_operations","process_operations","ops","operation_list"]

for cname, parts in containers:
    print("\n" + "=" * 80)
    print(f"CONTAINER: {cname}  ({len(parts)} parts)")
    print("=" * 80)
    for p in parts:
        if not isinstance(p, dict): continue
        pn = str(p.get("part_number") or p.get("part_no") or "?").upper()
        # only show parts of interest: those with holes or SEE-finishes anywhere
        fin_vals = {k: p.get(k) for k in FINISH_KEYS if p.get(k) is not None}
        op_vals  = {k: p.get(k) for k in OP_KEYS if p.get(k) is not None}
        # hole signal from geometry
        geo = p.get("geometry") or {}
        holes = geo.get("estimated_hole_count") or geo.get("estimated_pierce_count") or 0
        # does any op string mention hole/drill/punch?
        op_blob = " ".join(str(v) for v in op_vals.values()).lower()
        has_hole_op = any(t in op_blob for t in ("hole","drill","punch"))
        # does any finish mention SEE / powder / coat?
        fin_blob = " ".join(str(v) for v in fin_vals.values()).upper()
        has_see = "SEE " in fin_blob
        has_coat = "POWDER" in fin_blob or "COAT" in fin_blob
        if holes or has_hole_op or has_see or has_coat:
            print(f"\n  {pn}")
            print(f"    geometry holes/pierces : {holes}")
            print(f"    finish fields          : {fin_vals}")
            print(f"    operation fields       : {op_vals}")
            print(f"    -> has_hole_op={has_hole_op}  has_SEE_finish={has_see}  has_coat={has_coat}")

# Also: check the process_estimate labour lines for any coating/hole ops in 1282
print("\n" + "=" * 80)
print("1282 labour/process operations actually COSTED (coating + hole check)")
print("=" * 80)
for cname, parts in containers:
    for p in parts:
        if not isinstance(p, dict): continue
        pn = str(p.get("part_number") or "?").upper()
        pe = p.get("process_estimate") or {}
        ops = pe.get("operations") or pe.get("labour_lines") or pe.get("labour") or []
        for op in (ops if isinstance(ops, list) else []):
            if isinstance(op, dict):
                nm = str(op.get("operation") or op.get("name") or "").lower()
                if any(t in nm for t in ("coat","powder","hole","drill","punch","guill")):
                    print(f"  [{cname}] {pn}: op={nm!r} hours={op.get('hours') or op.get('total_hours')} cost={op.get('cost') or op.get('labour_cost_gbp')}")
    break  # first container with process_estimate is enough
