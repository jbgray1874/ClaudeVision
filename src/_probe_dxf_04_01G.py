#!/usr/bin/env python3
r"""
_probe_dxf_04_01G.py  —  READ-ONLY.

The engine put blank 2106 x 1378mm on the sheet for 12532-04-01G, breaking nesting
(#VALUE!). But the DXF is really ~668 x 200mm (matches the VINYL-668X200 display board
it carries). So the blank-dimension extraction misread this DXF by ~3x in each axis.

This probe opens the DXF with ezdxf and reports, WITHOUT going through the engine:
  - the overall bounding box of ALL entities (what the extents actually are)
  - the bounding box per LAYER (a border/frame on one layer can blow up the extents)
  - entity counts by type and by layer
  - the largest single entity's bounds (is there one giant rectangle = a border/sheet?)
  - INSERT/blocks (a title block or sheet frame inserted as a block inflates extents)
  - any entity far from the origin (stray geometry / dimension lines / viewport)

Goal: see whether 2106 x 1378 is a REAL part bound or an artefact (border, title block,
dimension, stray line) that the engine's blank logic wrongly took as the part extent.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_dxf_04_01G.py ^
   "\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\12532-03RecipeCard\12532-04-01G_revA .dxf"
"""
import sys

def main(path):
    try:
        import ezdxf
    except ImportError:
        sys.exit("ezdxf not installed in this interpreter — run with the engine venv.")

    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        sys.exit(f"could not read DXF: {e!r}")

    msp = doc.modelspace()
    print("=" * 88)
    print("DXF GEOMETRY PROBE — 12532-04-01G")
    print(f"file: {path}")
    print("=" * 88)
    print(f"DXF version: {doc.dxfversion}   units(insunits): {doc.header.get('$INSUNITS')}")

    # overall + per-layer bounds
    import math
    def bounds_of(entities):
        xmin=ymin=math.inf; xmax=ymax=-math.inf; n=0
        for e in entities:
            try:
                pts = []
                dt = e.dxftype()
                if dt == "LINE":
                    pts = [e.dxf.start, e.dxf.end]
                elif dt in ("LWPOLYLINE","POLYLINE"):
                    pts = [v[:2] if isinstance(v,(tuple,list)) else (v[0],v[1]) for v in e.get_points()] if dt=="LWPOLYLINE" else [(p.dxf.location.x,p.dxf.location.y) for p in e.vertices]
                elif dt == "CIRCLE":
                    c=e.dxf.center; r=e.dxf.radius; pts=[(c[0]-r,c[1]-r),(c[0]+r,c[1]+r)]
                elif dt == "ARC":
                    c=e.dxf.center; r=e.dxf.radius; pts=[(c[0]-r,c[1]-r),(c[0]+r,c[1]+r)]
                elif dt in ("INSERT","TEXT","MTEXT"):
                    p=e.dxf.insert; pts=[(p[0],p[1])]
                else:
                    try:
                        p=e.dxf.insert; pts=[(p[0],p[1])]
                    except Exception:
                        pts=[]
                for p in pts:
                    x,y=p[0],p[1]
                    xmin=min(xmin,x); ymin=min(ymin,y); xmax=max(xmax,x); ymax=max(ymax,y); n+=1
            except Exception:
                pass
        if n==0: return None
        return (xmin,ymin,xmax,ymax,xmax-xmin,ymax-ymin,n)

    allb = bounds_of(msp)
    if allb:
        print(f"\nOVERALL extents: X[{allb[0]:.1f}..{allb[2]:.1f}] Y[{allb[1]:.1f}..{allb[3]:.1f}]"
              f"  => W={allb[4]:.1f} x H={allb[5]:.1f} mm  ({allb[6]} pts)")
        print("  (engine used 2106 x 1378 — compare to this)")

    # per-layer
    print("\nPER-LAYER extents (a border/frame on its own layer will stand out):")
    layers = {}
    for e in msp:
        layers.setdefault(e.dxf.layer, []).append(e)
    for lname, ents in sorted(layers.items(), key=lambda kv: -len(kv[1])):
        b = bounds_of(ents)
        if b:
            print(f"  layer {lname!r:<22} {len(ents):>4} ents  W={b[4]:.1f} x H={b[5]:.1f}")

    # entity type counts
    print("\nENTITY TYPE COUNTS:")
    types={}
    for e in msp: types[e.dxftype()]=types.get(e.dxftype(),0)+1
    for t,c in sorted(types.items(), key=lambda kv:-kv[1]):
        print(f"  {t:<14} {c}")

    # INSERTs / blocks
    inserts=[e for e in msp if e.dxftype()=="INSERT"]
    if inserts:
        print(f"\nINSERTS (blocks — title blocks/frames inflate extents): {len(inserts)}")
        for e in inserts[:10]:
            print(f"  block {e.dxf.name!r} at ({e.dxf.insert[0]:.1f},{e.dxf.insert[1]:.1f})")

    # largest single closed polyline (candidate 'part outline' vs 'border')
    print("\nLARGEST LWPOLYLINE bounds (part outline candidate vs a border rectangle):")
    polys=[e for e in msp if e.dxftype()=="LWPOLYLINE"]
    sized=[]
    for e in polys:
        b=bounds_of([e])
        if b: sized.append((b[4]*b[5], b[4], b[5], e.dxf.layer, e.closed if hasattr(e,'closed') else '?'))
    for area,w,h,lay,closed in sorted(sized, reverse=True)[:6]:
        print(f"  W={w:.1f} x H={h:.1f}  layer={lay!r} closed={closed}")

    print("\n" + "=" * 88)
    print("READ: if OVERALL is ~2106x1378 but the biggest PART polyline is ~668x200,")
    print("then the engine took the wrong extent (border/frame/stray entity) as the blank.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_dxf_04_01G.py <path to dxf>"); sys.exit(1)
    main(sys.argv[1])
