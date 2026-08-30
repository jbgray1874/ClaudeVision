r"""READ-ONLY. The labour route table shows Manual £ as 0.00 for every op (WRONG — Tim booked
real costs). My field mapping is wrong for the REAL bundle. Dump the actual field values on a
few labour_route_comparisons rows so I map the right fields:
  - which field holds Tim's COST (should be ~13.62 for powder)
  - which holds Tim's HOURS
  - which holds engine cost + engine hours
Print raw dict for powder/folding/packing rows. No edits."""
import json
b=r"C:\ClaudeVision\output\csv\1282_parity_bundle.json"
J=json.load(open(b,encoding="utf-8"))
rows=[r for r in (J.get("labour_route_comparisons") or []) if r.get("section")=="labour_route"]

want=("powder","fold","pack","weld","laser")
print("Raw labour_route rows for key operations:\n")
for r in rows:
    disp=str(r.get("display_label") or r.get("canonical_operation") or "").lower()
    if any(w in disp for w in want):
        print(f"=== {r.get('display_label')} (canon={r.get('canonical_operation')}) status={r.get('status')} ===")
        for k in sorted(r.keys()):
            v=r[k]
            if v not in (None,"",[],{}):
                print(f"    {k} = {v}")
        print()

# also show ALL keys present on a populated row so I see every candidate field
pop=[r for r in rows if r.get("status")=="info"]
if pop:
    print("ALL keys on a populated (info) row:", sorted(pop[0].keys()))
