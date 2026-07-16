"""READ-ONLY diagnostic. Answers three things before we touch code:

  A. WHY did powder-coat not cost on 1298-01?
     - what finish did it detect? did 'SEE INDIVIDUAL DRAWINGS' resolve to powder-coat?
     - is there a powder_coating operation? what are its hours/cost?
     - is powder MATERIAL present?
     -> tells us if this is a clean finish-resolution fix (do now) or structural (log).

  B. WHERE is hole_machining / drilling emitted, and how does it map (or fall through)?
     - grep the op-detection + OP_NAME_MAP so we fold metal holes into laser at the right place.

  C. REGRESSION GUARD: how does 1282 handle the same patterns today?
     - do 1282 parts carry hole_machining? (if so, the fix changes 1282 -> must reconcile)
     - how does 1282 resolve 'SEE ASSEMBLY DRAWING' finishes into coating?
"""
import io, json, re
from pathlib import Path

SRC = Path(r"C:\ClaudeVision\src")
J1298 = Path(r"C:\ClaudeVision\output\json\1298DrillHolder.json")
J1282 = Path(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json")

def load(p):
    try: return json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        print(f"  could not load {p.name}: {e}"); return {}

def parts_of(d):
    return (d.get("manufacturing_writeup") or {}).get("parts") or d.get("parts") or []

print("=" * 80)
print("A. 1298-01 — finish, coating operation, powder material")
print("=" * 80)
d = load(J1298)
for p in parts_of(d):
    pn = str(p.get("part_number","")).upper()
    if pn != "1298-01":
        continue
    print(f"  part {pn}")
    print(f"    finishes (raw)        : {p.get('finishes')}")
    print(f"    normalized_finish     : {p.get('normalized_finish')}")
    print(f"    operations            : {p.get('operations')}")
    # process estimate / labour lines
    pe = p.get("process_estimate") or {}
    ops = pe.get("operations") or pe.get("labour") or pe.get("labour_lines") or []
    print(f"    process_estimate op keys: {list(pe.keys())[:12]}")
    for op in (ops if isinstance(ops, list) else []):
        if isinstance(op, dict):
            name = op.get("operation") or op.get("name") or op.get("op")
            hrs = op.get("hours") or op.get("total_hours")
            cost = op.get("cost") or op.get("labour_cost_gbp")
            if name and ("coat" in str(name).lower() or "powder" in str(name).lower() or "p.c" in str(name).lower()):
                print(f"    -> COATING op: {name} hours={hrs} cost={cost}")
    # material — powder consumable?
    me = p.get("material_estimate") or {}
    print(f"    material keys          : {[k for k in me.keys() if 'powder' in k.lower() or 'coat' in k.lower() or 'consum' in k.lower()]}")
    print(f"    powder_consumable      : {me.get('powder_consumable')}")

print("\n" + "=" * 80)
print("B. Where is hole_machining / drilling emitted + how it maps")
print("=" * 80)
for fn in ("operation_normaliser.py", "geometry_inference.py", "geometry_features.py",
           "extractor_patterns.py", "wb_populate.py", "config.py"):
    fp = SRC / fn
    if not fp.exists(): continue
    txt = fp.read_text(encoding="utf-8", errors="replace")
    hits = [(i,l) for i,l in enumerate(txt.splitlines(),1)
            if re.search(r"hole_machining|drilling|OP_NAME_MAP|hole.*op|drill", l, re.I)]
    if hits:
        print(f"  --- {fn} ---")
        for i,l in hits[:12]:
            print(f"    {i:5}: {l.strip()[:105]}")

print("\n" + "=" * 80)
print("C. REGRESSION GUARD — how 1282 handles holes + 'SEE ASSEMBLY' coating")
print("=" * 80)
d2 = load(J1282)
hole_parts = []
coat_via_assembly = []
for p in parts_of(d2):
    pn = str(p.get("part_number","")).upper()
    ops = [str(o).lower() for o in (p.get("operations") or [])]
    if any("hole" in o or "drill" in o for o in ops):
        hole_parts.append((pn, p.get("operations")))
    fin = str(p.get("finishes") or "").upper()
    if "SEE ASSEMBLY" in fin or "SEE INDIVIDUAL" in fin:
        coat_via_assembly.append((pn, p.get("finishes"), p.get("normalized_finish")))
print(f"  1282 parts carrying a hole/drill op: {len(hole_parts)}")
for pn, ops in hole_parts:
    print(f"     {pn}: {ops}")
print(f"\n  1282 parts with deferred 'SEE ...' finish: {len(coat_via_assembly)}")
for pn, fin, nf in coat_via_assembly:
    print(f"     {pn}: finish={fin} -> normalized={nf}")
print("\n  -> If 1282 has hole ops, folding them into laser CHANGES 1282's total -> reconcile, don't blind-accept.")
print("  -> If 1282's 'SEE ASSEMBLY' parts DO get coated (via assembly), that's the mechanism 1298 (single part) lacks.")
