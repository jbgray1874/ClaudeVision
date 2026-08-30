"""READ-ONLY. Definitive check: are the electricals/bought-ins sitting in the
'fabricated' set with the wrong tag, dragging BOTH halves of the credibility gate?

Answers three questions from 1282's ACTUAL JSON (no inference):
  1. For every part: what is normalized_material LITERALLY? Is it "BOUGHT_IN" or something else?
  2. Reconstruct the gate's 'fabricated' set the way the gate does (by normalized_material),
     and separately the way it SHOULD be (by any bought-in signal). Compare.
  3. Show which parts have a DXF, so we see the true DXF-coverage denominator both ways.

This shows definitively whether the root cause is "no path writes normalized_material=BOUGHT_IN".

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _boughtin_tag_probe.py
"""
import json, io

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(io.open(P, encoding="utf-8"))
parts = (data.get("manufacturing_writeup") or {}).get("parts") or data.get("parts") or []

def norm_mat(p):
    return str(p.get("normalized_material") or "").strip().upper()

def boughtin_by_any_signal(p):
    """The RELIABLE test: is this part bought-in by ANY recognition path?"""
    pn = str(p.get("part_number","")).upper()
    roles = [str(r).lower() for r in (p.get("page_roles") or [])]
    return (
        pn.startswith(("BI-","FIXING","VINYL","PACKAGING","DELIVERY"))
        or "bought_in" in roles
        or norm_mat(p) == "BOUGHT_IN"
        or bool(p.get("is_bought_in"))
        or bool(p.get("bought_in"))
        or "bought" in str(p.get("source") or "").lower()
    )

def has_dxf(p):
    return bool(p.get("dxf_augmented")) or "dxf" in str(p.get("geometry_source","")).lower()

print("=" * 92)
print("1. LITERAL normalized_material per part  (is bought-in-ness written onto the field?)")
print("=" * 92)
print(f"{'part':16} {'normalized_material':22} {'page_roles':18} {'by_any_signal':13} {'dxf':4}")
for p in parts:
    pn = str(p.get("part_number","—"))
    print(f"{pn:16} {norm_mat(p) or '(blank)':22} {str(p.get('page_roles') or []):18} "
          f"{'BOUGHT-IN' if boughtin_by_any_signal(p) else 'fabricated':13} {'yes' if has_dxf(p) else 'no':4}")

print("\n" + "=" * 92)
print("2. The gate's denominator TWO ways")
print("=" * 92)
# Way A: how a naive gate sees it — 'fabricated' = normalized_material != BOUGHT_IN
gate_fab = [p for p in parts if norm_mat(p) != "BOUGHT_IN"]
# Way B: the correct view — fabricated = NOT bought-in by any signal
true_fab = [p for p in parts if not boughtin_by_any_signal(p)]

gate_fab_dxf = [p for p in gate_fab if has_dxf(p)]
true_fab_dxf = [p for p in true_fab if has_dxf(p)]

print(f"  GATE view (by normalized_material only):")
print(f"     fabricated count = {len(gate_fab)}   with DXF = {len(gate_fab_dxf)}   "
      f"coverage = {100*len(gate_fab_dxf)/len(gate_fab):.0f}%" if gate_fab else "  (none)")
print(f"     misclassified bought-ins IN this set: "
      f"{[str(p.get('part_number')) for p in gate_fab if boughtin_by_any_signal(p)]}")
print()
print(f"  CORRECT view (exclude all bought-in signals):")
print(f"     fabricated count = {len(true_fab)}   with DXF = {len(true_fab_dxf)}   "
      f"coverage = {100*len(true_fab_dxf)/len(true_fab):.0f}%" if true_fab else "  (none)")

print("\n" + "=" * 92)
print("3. VERDICT")
print("=" * 92)
misclassified = [str(p.get("part_number")) for p in gate_fab if boughtin_by_any_signal(p)]
if misclassified:
    print(f"  BUG CONFIRMED: {len(misclassified)} bought-in part(s) are in the gate's 'fabricated'")
    print(f"  set because normalized_material is NOT 'BOUGHT_IN' on them:")
    print(f"    {misclassified}")
    print(f"  -> They drag the DXF-coverage denominator (they can never have a DXF) AND the")
    print(f"     cost credibility ratio. Console said '14 fabricated, 71%'.")
    print(f"     Gate sees {len(gate_fab)} fab / {100*len(gate_fab_dxf)/len(gate_fab):.0f}%;"
          f" correct is {len(true_fab)} fab / {100*len(true_fab_dxf)/len(true_fab):.0f}%.")
    print(f"  ROOT CAUSE: no recognition path writes normalized_material='BOUGHT_IN'.")
    print(f"  FIX DIRECTION: stamp it once at each recognition path (single source of truth).")
else:
    print(f"  NO misclassification: every bought-in already excluded from the gate's fabricated set.")
    print(f"  -> denominator is clean; the 43% is a genuine POLICY threshold, not a tagging bug.")
