import sys, math
from pathlib import Path
sys.path.insert(0, r"C:\ClaudeVision\src")
import ezdxf
from shapely.ops import polygonize, unary_union
from shapely.geometry import LineString

def scale_of(doc):
    u = int(doc.header.get("$INSUNITS",0) or 0)
    return {0:1.0,1:25.4,2:304.8,4:1.0,5:10.0,6:1000.0}.get(u,1.0)

# focus on the parts that returned polys=0 but SHOULD close
for name in ("1148 - Upper Leg Spigot.DXF", "3886-02_1.2mm_MS.DXF"):
    folder = Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay")
    hits = list(folder.rglob(name))
    if not hits: 
        print(name, "NOT FOUND"); continue
    doc = ezdxf.readfile(str(hits[0])); s = scale_of(doc); msp = doc.modelspace()
    print(f"\n=== {name}  scale={s} ===")
    segs=[]; endpoints=[]
    for e in msp:
        t=e.dxftype()
        if t=="LINE":
            a=(round(e.dxf.start.x*s,3),round(e.dxf.start.y*s,3)); b=(round(e.dxf.end.x*s,3),round(e.dxf.end.y*s,3))
            segs.append(LineString([a,b])); endpoints += [a,b]
            print(f"  LINE  {a} -> {b}")
        elif t=="ARC":
            try:
                pts=[(round(p.x*s,3),round(p.y*s,3)) for p in e.flattening(0.2/max(s,1e-9))]
                print(f"  ARC   r={getattr(e.dxf,'radius',0):.1f} start={pts[0]} end={pts[-1]} ({len(pts)} pts)")
                for i in range(len(pts)-1): segs.append(LineString([pts[i],pts[i+1]]))
                endpoints += [pts[0],pts[-1]]
            except Exception as ex:
                print(f"  ARC   FLATTEN FAILED: {ex}")
    merged=unary_union(segs); polys=list(polygonize(merged))
    print(f"  -> {len(segs)} segments, polygonize found {len(polys)} polygon(s)")
    # find nearest-neighbour gaps between distinct endpoints (why it won't close)
    uniq=list(set(endpoints))
    gaps=[]
    for i,p in enumerate(uniq):
        d=min((math.dist(p,q) for j,q in enumerate(uniq) if j!=i), default=0)
        gaps.append(d)
    gaps.sort(reverse=True)
    print(f"  largest endpoint-to-endpoint gaps (mm): {[round(g,3) for g in gaps[:5]]}")
    print(f"  (if any gap >> 0, the ring is broken there — noding/flattening leaves a hole)")
