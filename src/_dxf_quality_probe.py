# -*- coding: utf-8 -*-
r"""Read-only DXF quality probe. Answers two questions against the real 1282 DXFs:
  1. INSERT blocks: are there any? Does exploding them change the geometry/extents?
     (This is the prime suspect for James Ryan's 'dimensions slightly off' defect.)
  2. Manufacturing routing: what layers / entity types / text actually exist in the DXF?
     Is there explicit route/operation/machine data, or only geometry we must infer from?
Run:
  C:\ClaudeVision\.venv\Scripts\python.exe C:\ClaudeVision\src\_dxf_quality_probe.py
"""
from pathlib import Path
from collections import Counter
try:
    import ezdxf
    from ezdxf import bbox
except Exception as e:
    print("ezdxf not available:", e); raise SystemExit(1)

JOB = Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay")
dxfs = sorted(JOB.glob("*.dxf")) + sorted(JOB.glob("*.DXF"))
print(f"DXF files found: {len(dxfs)}\n")

def extents_of(entities):
    try:
        ext = bbox.extents(entities)
        if ext is None: return None
        w = ext.size.x; h = ext.size.y
        return (round(w,2), round(h,2))
    except Exception as ex:
        return f"err:{ex}"

for path in dxfs:
    try:
        doc = ezdxf.readfile(str(path))
    except Exception as ex:
        print(f"--- {path.name}: READ ERROR {ex}"); continue
    msp = doc.modelspace()
    ents = list(msp)
    types = Counter(e.dxftype() for e in ents)
    layers = Counter(str(getattr(e.dxf, "layer", "")) for e in ents)
    inserts = [e for e in ents if e.dxftype() == "INSERT"]

    print(f"=== {path.name} ===")
    print(f"  units (INSUNITS): {doc.header.get('$INSUNITS', 'unset')}")
    print(f"  entity types: {dict(types)}")
    print(f"  layers: {dict(layers)}")

    # (1) INSERT explosion impact on extents
    ext_raw = extents_of(msp)
    print(f"  INSERT count: {len(inserts)}")
    if inserts:
        # build a virtual entity list = non-INSERT entities + exploded virtual entities
        virt = [e for e in ents if e.dxftype() != "INSERT"]
        exploded = 0
        for ins in inserts:
            try:
                for ve in ins.virtual_entities():
                    virt.append(ve); exploded += 1
            except Exception as ex:
                print(f"    explode err on INSERT: {ex}")
        ext_exploded = extents_of(virt)
        print(f"  extents model-space only : {ext_raw}")
        print(f"  extents with INSERTs expl: {ext_exploded}  (+{exploded} virtual entities)")
        if ext_raw and ext_exploded and isinstance(ext_raw, tuple) and isinstance(ext_exploded, tuple):
            dw = abs(ext_raw[0]-ext_exploded[0]); dh = abs(ext_raw[1]-ext_exploded[1])
            flag = "  <<< DIFFERENT — INSERT explosion changes size!" if (dw>0.5 or dh>0.5) else "  (same)"
            print(f"  delta: dW={round(dw,2)} dH={round(dh,2)}{flag}")
    else:
        print(f"  extents: {ext_raw}  (no INSERTs — explosion would not change this part)")

    # (2) Routing/operation signal: any text/layers naming machines/operations?
    route_words = ("LASER","PUNCH","BEND","FOLD","WELD","TUBE","DEBUR","FORM","TAP",
                   "ROUTE","OP ","CUT","NC","CAM","MACHINE","TOOL","V-","DIE")
    texts = []
    for e in ents:
        if e.dxftype() in ("TEXT","MTEXT"):
            try:
                t = e.plain_text() if hasattr(e,"plain_text") else str(e.dxf.get("text",""))
            except Exception:
                t = ""
            if t: texts.append(t.strip())
    hits = [t for t in texts if any(w in t.upper() for w in route_words)]
    route_layers = [l for l in layers if any(w in l.upper() for w in route_words)]
    print(f"  text entities: {len(texts)}; routing-ish text hits: {len(hits)}")
    for h in hits[:6]: print(f"     TEXT> {h[:70]}")
    print(f"  routing-ish layer names: {route_layers}")
    print()
