r"""
_shapely_recon_test.py  —  STANDALONE proof that a shapely polygonize reconstruction
fixes the broken shoelace net-area on SDI's loose LINE+ARC DXF exports. READ-ONLY:
reads the 14 DXFs, writes nothing, changes no live file.

The live dxf_reader.py.py computes blank_area_mm2 via _order_segments (endpoint-walk of
LINEs only, ignores ARCs) -> collapses to ~0 on any profile with curved corners/holes
(peg panel = 90mm2 for a 553x525 part). This rebuilds the outer contour + holes with:
  1. ezdxf arc.flattening() so curved edges become short segments
  2. shapely.ops.polygonize on ALL cut-layer LINE + flattened-ARC segments (node-based
     stitching that tolerates the messy soup endpoint-walking can't)
  3. outer = largest polygon; interior loops + CIRCLE entities = holes
  4. net_area = outer.area - sum(hole areas)
  5. bbox_fill sanity gate: net_area must be a sane fraction of bbox, else ABSTAIN->bbox+flag

Prints, per part: bbox area, OLD broken shoelace area, NEW shapely net area, fill%,
and a verdict. The peg panel + complex 1455 parts must go from garbage -> sensible.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _shapely_recon_test.py "K:\...\1282 - Milwaukee Wall Bay"
"""
import sys, math
from pathlib import Path

try:
    import ezdxf
except Exception as e:
    sys.exit(f"ezdxf not importable: {e}")
try:
    from shapely.ops import polygonize, unary_union
    from shapely.geometry import LineString, Polygon, Point
except Exception as e:
    sys.exit(f"shapely not importable: {e}")

# same CUT layers the live extractor uses
CUT_LAYERS = {"SLD-0", "0", "VISIBLE EDGES(BENCHMARK)"}
SKIP_LAYERS = {"BENDLINES", "BEND", "BEND_LINES", "DIMS+NOTES", "SKETCHES",
               "DEFPOINTS", "DIMENSIONS(BENCHMARK)", "SYMBOLS(BENCHMARK)"}
ARC_SAG_MM = 0.20   # flattening chord tolerance (mm) — fine enough for area, cheap


def _layer(e):
    return str(getattr(e.dxf, "layer", "") or "").upper()


def _insunits_scale(doc):
    u = int(doc.header.get("$INSUNITS", 0) or 0)
    return {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}.get(u, 1.0), u


def _cut_segments(msp, scale):
    """All cut LINE + flattened-ARC + polyline segments as shapely LineStrings (mm).
    Skip ONLY true annotation/bend layers; process everything else (SDI puts the whole
    profile on '0'/'SLD-0'). Proven necessary: gating arcs by a CUT_LAYERS whitelist left
    arc-cornered profiles open -> polygonize found nothing. Correctness first, refine later."""
    segs = []
    skip = {l.upper() for l in SKIP_LAYERS}
    for e in msp:
        if _layer(e) in skip:
            continue
        t = e.dxftype()
        try:
            if t == "LINE":
                a = (e.dxf.start.x * scale, e.dxf.start.y * scale)
                b = (e.dxf.end.x * scale, e.dxf.end.y * scale)
                if math.dist(a, b) > 1e-6:
                    segs.append(LineString([a, b]))
            elif t == "ARC":
                pts = [(v.x * scale, v.y * scale) for v in e.flattening(ARC_SAG_MM / max(scale, 1e-9))]
                for i in range(len(pts) - 1):
                    if math.dist(pts[i], pts[i + 1]) > 1e-6:
                        segs.append(LineString([pts[i], pts[i + 1]]))
            elif t in ("LWPOLYLINE", "POLYLINE"):
                pts = [(x * scale, y * scale) for x, y, *_ in e.get_points("xy")]
                for i in range(len(pts) - 1):
                    if math.dist(pts[i], pts[i + 1]) > 1e-6:
                        segs.append(LineString([pts[i], pts[i + 1]]))
                if getattr(e, "closed", False) and len(pts) > 2:
                    segs.append(LineString([pts[-1], pts[0]]))
        except Exception:
            continue
    return segs


def _circle_holes(msp, scale):
    holes = []
    skip = {l.upper() for l in SKIP_LAYERS}
    for e in msp:
        if e.dxftype() == "CIRCLE" and _layer(e) not in skip:
            r = float(getattr(e.dxf, "radius", 0.0) or 0.0) * scale
            if r >= 0.5:
                c = (e.dxf.center.x * scale, e.dxf.center.y * scale)
                holes.append(Point(c).buffer(r, resolution=16))
    return holes


def _bbox_area(segs):
    xs, ys = [], []
    for s in segs:
        for x, y in s.coords:
            xs.append(x); ys.append(y)
    if not xs:
        return 0.0, 0.0, 0.0
    L, W = max(xs) - min(xs), max(ys) - min(ys)
    return max(L, W), min(L, W), (L * W)


def recon(dxf_path):
    doc = ezdxf.readfile(str(dxf_path))
    scale, insunits = _insunits_scale(doc)
    msp = doc.modelspace()
    segs = _cut_segments(msp, scale)
    if not segs:
        return None
    bl, bw, bbox_area = _bbox_area(segs)

    # node-based polygonization of the whole cut-segment soup. snap() first collapses
    # near-coincident endpoints (CAD exports often have sub-micron gaps at corners) so the
    # ring closes; then unary_union nodes intersections and polygonize builds faces.
    from shapely.ops import snap as _snap
    net = unary_union(segs)
    try:
        net = _snap(net, net, 0.05)            # 0.05 mm weld tolerance
    except Exception:
        pass
    merged = unary_union(net)
    polys = list(polygonize(merged))
    net_area = 0.0
    n_poly = len(polys)
    if polys:
        outer = max(polys, key=lambda p: p.area)
        interior = [p for p in polys if p is not outer]
        holes_area = sum(p.area for p in interior)
        net_area = max(0.0, outer.area - holes_area)
        # subtract CIRCLE holes not captured as polygons
        circ = _circle_holes(msp, scale)
        if circ:
            circ_in_outer = sum(c.area for c in circ if outer.contains(c.representative_point()))
            net_area = max(0.0, net_area - circ_in_outer)

    fill = (100.0 * net_area / bbox_area) if bbox_area > 0 else 0.0
    # abstain gate: a real sheet-metal blank fills a sane fraction of its bbox
    ok = 30.0 <= fill <= 100.5
    return {
        "insunits": insunits, "bl": round(bl, 1), "bw": round(bw, 1),
        "bbox_area": round(bbox_area, 1), "net_area": round(net_area, 1),
        "fill": round(fill, 1), "n_poly": n_poly, "ok": ok,
    }


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    dxfs = sorted(set(list(folder.rglob("*.DXF")) + list(folder.rglob("*.dxf"))))
    print(f"{'part':<44}{'bbox area':<12}{'NEW net':<12}{'fill%':<8}{'polys':<7}{'verdict'}")
    print("-" * 100)
    for d in dxfs:
        try:
            r = recon(d)
            if r is None:
                print(f"{d.name[:43]:<44}{'—':<12}{'—':<12}{'—':<8}{'—':<7}no cut segments")
                continue
            verdict = "OK" if r["ok"] else ("ABSTAIN->bbox+flag" if r["fill"] < 30 else "check")
            print(f"{d.name[:43]:<44}{r['bbox_area']:<12}{r['net_area']:<12}"
                  f"{r['fill']:<8}{r['n_poly']:<7}{verdict}"
                  + ("" if r['insunits'] != 0 else "  [INSUNITS=0!]"))
        except Exception as e:
            print(f"{d.name[:43]:<44}ERROR: {e}")
    print("\nRead-only. Compare NEW net vs the OLD broken shoelace (peg panel was 90mm2,")
    print("1455-C-001 was 2mm2). A correct net area is a sane fraction of bbox (fill 30-100%).")
    print("Parts that still can't close -> ABSTAIN to bbox + flag (never pass garbage through).")


if __name__ == "__main__":
    main()
