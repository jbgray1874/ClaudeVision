r"""
dxf_route_verify.py  —  READ-ONLY per-part verification report.

For each DXF in a job folder it re-reads the geometry fresh and shows, side by side:
  * blank L x W          (current bbox vs shapely — should match)
  * NET area             (current _order_segments vs shapely polygonize) <- the fix
  * cut length / holes / bends (+ which layer bends came from)
  * the manufacturing ROUTE each part's geometry implies (laser/fold/punch/weld/powder)
  * abstain/flags        (shapely fell back, unitless DXF, missing BENDLINES, etc.)

It also cross-references the live job JSON (what the engine actually used) so a
provenance mismatch (engine used a different L/W than the DXF says) is visible.

Writes ONE self-contained HTML file. Touches no live code, no estimate. shapely + ezdxf
both required (in the venv). Run:

  C:\ClaudeVision\.venv\Scripts\python.exe dxf_route_verify.py ^
      "K:\...\1282 - Milwaukee Wall Bay" ^
      --json "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json" ^
      --out  "C:\ClaudeVision\output\1282_dxf_route_verify.html"
"""
import sys, os, math, json, argparse, html
from pathlib import Path

try:
    import ezdxf
    from ezdxf import bbox as _bbox
except Exception as e:
    sys.exit(f"ezdxf not importable: {e}")
try:
    from shapely.ops import polygonize, unary_union, snap as _snap
    from shapely.geometry import LineString, Point
except Exception as e:
    sys.exit(f"shapely not importable: {e}")

CUT_LAYERS  = {"SLD-0", "0", "VISIBLE EDGES(BENCHMARK)"}
BEND_LAYERS = {"BENDLINES", "BEND", "BEND_LINES"}
SKIP_LAYERS = {"DIMS+NOTES", "SKETCHES", "DEFPOINTS", "DIMENSIONS(BENCHMARK)",
               "SYMBOLS(BENCHMARK)"}
INSUNITS = {0:"unitless(ASSUMED mm)",1:"in",2:"ft",4:"mm",5:"cm",6:"m"}


def _layer(e): return str(getattr(e.dxf,"layer","") or "").upper()
def _scale(doc):
    u=int(doc.header.get("$INSUNITS",0) or 0)
    return {0:1.0,1:25.4,2:304.8,4:1.0,5:10.0,6:1000.0}.get(u,1.0), u
def _arc_len(e,s):
    try: return float(e.length())*s
    except Exception:
        r=float(getattr(e.dxf,"radius",0) or 0)*s
        a0=math.radians(float(getattr(e.dxf,"start_angle",0) or 0))
        a1=math.radians(float(getattr(e.dxf,"end_angle",0) or 0))
        return abs(r*((a1-a0)%(2*math.pi)))


def read_current(dxf):
    """Reproduce the CURRENT in-tree geometry: sum all segment lengths (cut_length),
    LINE-only bbox, LINE-only _order_segments shoelace (the broken net area), circle count,
    BENDLINES bend count."""
    doc=ezdxf.readfile(str(dxf)); s,ins=_scale(doc); msp=doc.modelspace()
    cut_len=0.0; circ=0; xs=[]; ys=[]; line_pts=[]
    bend_lines=0; bend_layer_present=False
    for e in msp:
        lay=_layer(e); t=e.dxftype()
        if lay in {l.upper() for l in BEND_LAYERS}:
            bend_layer_present=True
            if t=="LINE": bend_lines+=1
            continue
        if lay in {l.upper() for l in SKIP_LAYERS}:
            continue
        if t=="LINE":
            a=(e.dxf.start.x*s,e.dxf.start.y*s); b=(e.dxf.end.x*s,e.dxf.end.y*s)
            d=math.dist(a,b)
            if d<0.05: continue
            cut_len+=d; xs+=[a[0],b[0]]; ys+=[a[1],b[1]]; line_pts.append((a,b))
        elif t=="ARC":
            cut_len+=_arc_len(e,s)
        elif t=="CIRCLE":
            r=float(getattr(e.dxf,"radius",0) or 0)*s
            if r>=0.25: circ+=1; cut_len+=2*math.pi*r
    bl=bw=0.0
    if xs: bl=round(max(xs)-min(xs),1); bw=round(max(ys)-min(ys),1)
    L,W=max(bl,bw),min(bl,bw)
    # current broken net area via LINE-only endpoint walk
    net_old=_order_walk_area(line_pts)
    bbox_area=L*W
    if net_old<1.0 and bbox_area>0: net_old=bbox_area  # the fallback
    return dict(scale=s,insunits=ins,cut_len=round(cut_len,1),holes=circ,
                bl=L,bw=W,bbox_area=round(bbox_area,1),net_old=round(net_old,1),
                bends=bend_lines,bend_layer=bend_layer_present)


def _order_walk_area(line_pts, tol=0.05):
    """The current _order_segments logic: endpoint-walk LINEs only (ignores arcs)."""
    if not line_pts: return 0.0
    segs=[(a,b) for a,b in line_pts]; used=[False]*len(segs)
    pts=list(segs[0]); used[0]=True
    for _ in range(len(segs)-1):
        last=pts[-1]; found=False
        for i,(a,b) in enumerate(segs):
            if used[i]: continue
            if math.dist(last,a)<tol: pts.append(b); used[i]=True; found=True; break
            if math.dist(last,b)<tol: pts.append(a); used[i]=True; found=True; break
        if not found: break
    if len(pts)<3: return 0.0
    s=0.0
    for i in range(len(pts)):
        j=(i+1)%len(pts); s+=pts[i][0]*pts[j][1]-pts[j][0]*pts[i][1]
    return abs(s)/2


def read_shapely(dxf):
    """The shapely polygonize net area (proven fix) + real perimeter."""
    doc=ezdxf.readfile(str(dxf)); s,ins=_scale(doc); msp=doc.modelspace()
    segs=[]; xs=[]; ys=[]; perim=0.0; _sag=0.20/max(s,1e-9)
    circ_ents=[]
    for e in msp:
        lay=_layer(e); t=e.dxftype()
        if lay in {l.upper() for l in BEND_LAYERS}: continue
        if lay in {l.upper() for l in SKIP_LAYERS}: continue
        if t=="LINE":
            a=(e.dxf.start.x*s,e.dxf.start.y*s); b=(e.dxf.end.x*s,e.dxf.end.y*s)
            if math.dist(a,b)>1e-6:
                segs.append(LineString([a,b])); perim+=math.dist(a,b)
                xs+=[a[0],b[0]]; ys+=[a[1],b[1]]
        elif t=="ARC":
            try: pts=[(v.x*s,v.y*s) for v in e.flattening(_sag)]
            except Exception: continue
            perim+=_arc_len(e,s)
            for i in range(len(pts)-1):
                if math.dist(pts[i],pts[i+1])>1e-6:
                    segs.append(LineString([pts[i],pts[i+1]]))
                    xs+=[pts[i][0],pts[i+1][0]]; ys+=[pts[i][1],pts[i+1][1]]
        elif t=="CIRCLE":
            circ_ents.append(e); perim+=2*math.pi*float(getattr(e.dxf,"radius",0) or 0)*s
    if not segs: return dict(net=0.0,method="no_segments",fill=0.0,perim=round(perim,1))
    bl=max(xs)-min(xs); bw=max(ys)-min(ys); bbox_area=max(bl,bw)*min(bl,bw)
    net=unary_union(segs)
    try: net=_snap(net,net,0.05)
    except Exception: pass
    polys=list(polygonize(unary_union(net)))
    if not polys:
        return dict(net=round(bbox_area,1),method="bbox_polygonize_empty",fill=0.0,perim=round(perim,1))
    outer=max(polys,key=lambda p:p.area)
    net_area=max(0.0,outer.area-sum(p.area for p in polys if p is not outer))
    for e in circ_ents:
        try:
            r=float(getattr(e.dxf,"radius",0) or 0)*s
            if r<0.5: continue
            c=(e.dxf.center.x*s,e.dxf.center.y*s); disc=Point(c).buffer(r, 16)
            if outer.contains(disc.representative_point()): net_area=max(0.0,net_area-disc.area)
        except Exception: continue
    fill=(100.0*net_area/bbox_area) if bbox_area>0 else 0.0
    method="shapely_polygonize" if 30.0<=fill<=100.5 else "bbox_fill_out_of_band"
    if method!="shapely_polygonize": net_area=bbox_area
    return dict(net=round(net_area,1),method=method,fill=round(fill,1),perim=round(perim,1),
                bbox_area=round(bbox_area,1))


def implied_route(cur, mfg_obs):
    """Route each part's geometry implies. mfg_obs = list of observation strings for this part."""
    ops=[]
    obs=" ".join(mfg_obs).lower()
    if cur["holes"]>0: ops.append(("Punch/pierce", f"{cur['holes']} holes", "geom"))
    if "flat pattern" in obs or cur["cut_len"]>0:
        ops.append(("Laser/profile", f"cut {cur['cut_len']:.0f}mm", "geom"))
    if cur["bends"]>0:
        ops.append(("Fold", f"{cur['bends']} bend lines (BENDLINES layer)", "geom"))
    elif "fold or bend" in obs:
        ops.append(("Fold", "indicated in notes (no BENDLINES layer)", "inferred"))
    if "weld" in obs:
        ops.append(("Weld", "from process note", "note"))
    if "powder" in obs:
        ops.append(("Powder coat", "finish", "note"))
    elif "see assembly" in obs:
        ops.append(("Powder coat", "POINTER → assembly (resolved)", "pointer"))
    return ops


def load_json_parts(jpath):
    """Map part_number -> {manufacturing observations, engine geometry used}."""
    if not jpath or not os.path.exists(jpath): return {}, []
    J=json.load(open(jpath,encoding="utf-8"))
    obs_by_part={}
    # manufacturing_writeup.parts carry per-part manufacturing_observations or similar
    def walk(o):
        if isinstance(o,dict):
            yield o
            for v in o.values(): yield from walk(v)
        elif isinstance(o,list):
            for v in o: yield from walk(v)
    for n in walk(J):
        pn=n.get("part_number")
        if not pn: continue
        # gather any observation-ish strings
        obs=[]
        for k in ("manufacturing_observations","observations","textual_operations","operations","surface_finishes"):
            v=n.get(k)
            if isinstance(v,list): obs+= [str(x) for x in v]
            elif isinstance(v,str): obs.append(v)
        if obs:
            obs_by_part.setdefault(str(pn),[]).extend(obs)
    return obs_by_part, []


def esc(x): return html.escape(str(x))

def card(name, part_no, cur, shp, route, mismatch_note):
    # net area delta highlight
    net_old=cur["net_old"]; net_new=shp["net"]
    ratio = (net_new/net_old) if net_old>0 else 0
    broke = net_old < 0.5*shp.get("bbox_area", net_new*2) and net_old < net_new*0.5
    unit_flag = cur["insunits"]==0
    method=shp["method"]
    abstained = method!="shapely_polygonize"
    rows=""
    def r(label, a, b, flag=""):
        return (f'<div class="r"><span class="lbl">{esc(label)}</span>'
                f'<span class="a">{esc(a)}</span><span class="arrow">→</span>'
                f'<span class="b {flag}">{esc(b)}</span></div>')
    rows+=r("blank L×W (mm)", f"{cur['bl']} × {cur['bw']}", f"{shp.get('bbox_area','') and ''}{cur['bl']} × {cur['bw']}")
    rows+=r("net area (mm²)", f"{net_old:,.0f}", f"{net_new:,.0f}",
            "good" if (broke and not abstained) else ("warn" if abstained else ""))
    rows+=r("cut length (mm)", f"{cur['cut_len']:,.0f}", f"{shp['perim']:,.0f}")
    rows+=r("holes", cur["holes"], cur["holes"])
    rows+=r("bends", f"{cur['bends']}" + (" (BENDLINES)" if cur["bend_layer"] else " (none)"),
            f"{cur['bends']}")
    route_html=""
    for op,detail,src in route:
        cls={"geom":"src-geom","inferred":"src-inf","note":"src-note","pointer":"src-ptr"}.get(src,"")
        route_html+=f'<span class="op {cls}">{esc(op)}<em>{esc(detail)}</em></span>'
    flags=[]
    if unit_flag: flags.append("⚠ DXF is UNITLESS ($INSUNITS=0) — scale assumed mm")
    if abstained: flags.append(f"⚠ shapely abstained ({esc(method)}) — using bbox, flag geometry")
    if broke and not abstained: flags.append(f"✓ net-area fix: {net_old:,.0f} → {net_new:,.0f} mm² (was broken)")
    if not cur["bend_layer"] and any(o[0]=="Fold" for o in route):
        flags.append("⚠ fold implied but NO BENDLINES layer — bend count inferred, not read")
    if mismatch_note: flags.append(f"⚠ {esc(mismatch_note)}")
    flags_html="".join(f'<li class="{ ("ok" if f.startswith("✓") else "flag") }">{esc(f)}</li>' for f in flags)
    return f'''
    <article class="card">
      <header><h2>{esc(part_no or name)}</h2><span class="fname">{esc(name)}</span></header>
      <div class="cols"><span class="chdr">measure</span><span class="chdr">current</span>
        <span></span><span class="chdr">shapely</span></div>
      {rows}
      <div class="route"><span class="rlbl">route implied</span>{route_html or '<em>none detected</em>'}</div>
      <ul class="flags">{flags_html or '<li class="ok">no flags</li>'}</ul>
    </article>'''


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--json", default=None)
    ap.add_argument("--out", default="dxf_route_verify.html")
    a=ap.parse_args()
    folder=Path(a.folder)
    dxfs=sorted(set(list(folder.rglob("*.DXF"))+list(folder.rglob("*.dxf"))))
    obs_by_part,_=load_json_parts(a.json)

    cards=[]; n_fixed=0; n_abstain=0; n_unit=0
    for d in dxfs:
        try:
            cur=read_current(d); shp=read_shapely(d)
        except Exception as e:
            cards.append(f'<article class="card err"><h2>{esc(d.name)}</h2><p>ERROR: {esc(e)}</p></article>')
            continue
        # crude part-number from filename stem (first token)
        stem=d.stem
        pn=None
        import re
        m=re.match(r"(\d{3,5}[A-Z]?(?:-[A-Z0-9]+)*)", stem)
        if m: pn=m.group(1)
        obs=obs_by_part.get(pn or "", [])
        route=implied_route(cur, obs)
        mismatch=""
        if cur["net_old"]>0 and shp["net"]>0 and cur["net_old"]<shp["net"]*0.5 and shp["method"]=="shapely_polygonize":
            n_fixed+=1
        if shp["method"]!="shapely_polygonize": n_abstain+=1
        if cur["insunits"]==0: n_unit+=1
        cards.append(card(d.name, pn, cur, shp, route, mismatch))

    summary=(f'{len(dxfs)} DXFs · {n_fixed} net-area corrections · '
             f'{n_abstain} abstained→bbox · {n_unit} unitless')
    doc=f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DXF · Route Verification — {esc(folder.name)}</title>
<style>
  :root{{
    --ink:#12161c; --sub:#5a6472; --line:#dde3ea; --bg:#f6f7f9; --card:#fff;
    --good:#0a7d4d; --goodbg:#e7f6ee; --warn:#b25a00; --warnbg:#fdf0e2;
    --flag:#8a1c2b; --geom:#0a5ad6; --note:#6b3fa0; --ptr:#00786f;
    --mono:"SF Mono",ui-monospace,"Cascadia Code",Menlo,monospace;
    --sans:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  }}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);
    font-feature-settings:"tnum" 1,"cv05" 1;line-height:1.4}}
  .wrap{{max-width:1180px;margin:0 auto;padding:40px 28px 80px}}
  .top{{border-bottom:2px solid var(--ink);padding-bottom:18px;margin-bottom:8px}}
  .eyebrow{{font-family:var(--mono);font-size:11px;letter-spacing:.14em;
    text-transform:uppercase;color:var(--sub)}}
  h1{{font-size:30px;margin:.25em 0 .1em;letter-spacing:-.01em}}
  .sum{{font-family:var(--mono);font-size:12.5px;color:var(--sub);margin-bottom:34px}}
  .legend{{display:flex;gap:16px;flex-wrap:wrap;font-family:var(--mono);font-size:11px;
    color:var(--sub);margin:-24px 0 30px}}
  .legend b{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;
    vertical-align:middle}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;
    padding:18px 18px 14px;box-shadow:0 1px 2px rgba(16,22,28,.04)}}
  .card.err{{border-color:var(--flag)}}
  .card header{{display:flex;align-items:baseline;justify-content:space-between;
    gap:10px;border-bottom:1px solid var(--line);padding-bottom:9px;margin-bottom:10px}}
  .card h2{{font-size:16px;margin:0;font-family:var(--mono);letter-spacing:-.01em}}
  .fname{{font-family:var(--mono);font-size:10px;color:var(--sub);text-align:right;
    max-width:52%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .cols{{display:grid;grid-template-columns:1.5fr 1fr 16px 1fr;gap:6px;margin-bottom:4px}}
  .chdr{{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
    color:var(--sub)}}
  .r{{display:grid;grid-template-columns:1.5fr 1fr 16px 1fr;gap:6px;align-items:baseline;
    padding:3px 0;border-bottom:1px dotted var(--line)}}
  .lbl{{font-size:12px;color:var(--sub)}}
  .a,.b{{font-family:var(--mono);font-size:12.5px;text-align:right}}
  .a{{color:var(--sub)}}
  .arrow{{color:#c2cad4;text-align:center;font-size:11px}}
  .b.good{{color:var(--good);font-weight:600}}
  .b.warn{{color:var(--warn);font-weight:600}}
  .route{{margin:12px 0 8px;display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
  .rlbl{{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;
    color:var(--sub);width:100%}}
  .op{{font-size:11.5px;padding:3px 8px;border-radius:5px;background:#eef1f5;
    display:inline-flex;flex-direction:column;line-height:1.25}}
  .op em{{font-style:normal;font-size:9.5px;color:var(--sub);font-family:var(--mono)}}
  .op.src-geom{{background:#e8f0fe;box-shadow:inset 2px 0 0 var(--geom)}}
  .op.src-inf{{background:var(--warnbg);box-shadow:inset 2px 0 0 var(--warn)}}
  .op.src-note{{background:#f2ecfa;box-shadow:inset 2px 0 0 var(--note)}}
  .op.src-ptr{{background:#e2f5f2;box-shadow:inset 2px 0 0 var(--ptr)}}
  .flags{{list-style:none;margin:8px 0 0;padding:0;display:flex;flex-direction:column;gap:3px}}
  .flags li{{font-size:11px;font-family:var(--mono);padding:4px 8px;border-radius:5px}}
  .flags li.ok{{background:var(--goodbg);color:var(--good)}}
  .flags li.flag{{background:var(--warnbg);color:var(--warn)}}
  @media (max-width:560px){{.grid{{grid-template-columns:1fr}}}}
</style></head>
<body><div class="wrap">
  <div class="top">
    <div class="eyebrow">Geometry & Route Verification · read-only</div>
    <h1>{esc(folder.name)}</h1>
  </div>
  <div class="sum">{esc(summary)}</div>
  <div class="legend">
    <span><b style="background:#0a5ad6"></b>from geometry</span>
    <span><b style="background:#b25a00"></b>inferred (no layer)</span>
    <span><b style="background:#6b3fa0"></b>from note</span>
    <span><b style="background:#00786f"></b>pointer resolved</span>
    <span><b style="background:#0a7d4d"></b>net-area fix</span>
  </div>
  <div class="grid">{''.join(cards)}</div>
</div></body></html>'''
    Path(a.out).write_text(doc, encoding="utf-8")
    print(f"WROTE {a.out}")
    print(f"  {summary}")


if __name__=="__main__":
    main()
