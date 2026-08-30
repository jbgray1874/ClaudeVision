r"""
_dxf_inspector.py  —  READ-ONLY DXF inventory. Writes nothing, changes nothing.

Answers, per DXF and in aggregate, the questions that decide whether shapely can help
and where the current ezdxf geometry path is guessing:
  * entity-type counts (LINE / LWPOLYLINE / POLYLINE / CIRCLE / ARC / SPLINE / TEXT ...)
  * layer table (names — often carry bend/hole/outline intent)
  * closed-polyline count + how many are the OUTER contour vs interior loops (candidate holes)
  * $INSUNITS  — the mm-vs-unitless trap (0 = unitless => scale UNKNOWN, a red flag)
  * TEXT / MTEXT count — confirms the "DXF is geometry-only" assumption per file
  * a naive bounding box + naive net-area-by-shoelace, ONLY to show where the current
    heuristic (cut_len - bounding_perim) diverges from a real polygon area (shapely's job)

Usage (run on the SDI machine, points at a folder OR a single .dxf):
  C:\ClaudeVision\.venv\Scripts\python.exe _dxf_inspector.py "K:\...\1282 - Milwaukee Wall Bay"
  C:\ClaudeVision\.venv\Scripts\python.exe _dxf_inspector.py "C:\path\one_file.dxf"

Optional 2nd arg = a directory to also recurse for .dxf (e.g. a matched-DXF cache).
Requires ezdxf (already in the venv). shapely NOT required — this is pre-shapely triage.
"""
import sys, os, glob, math
from collections import Counter, defaultdict

try:
    import ezdxf
    from ezdxf import bbox
except Exception as e:  # pragma: no cover
    print(f"FATAL: ezdxf not importable in this interpreter ({e}).")
    sys.exit(1)


def _find_dxfs(root):
    if os.path.isfile(root) and root.lower().endswith(".dxf"):
        return [root]
    hits = []
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if f.lower().endswith(".dxf"):
                hits.append(os.path.join(dirpath, f))
    return sorted(hits)


def _poly_points(e):
    """Return the (x, y) vertices of an LWPOLYLINE or 2D POLYLINE, else None."""
    try:
        if e.dxftype() == "LWPOLYLINE":
            return [(p[0], p[1]) for p in e.get_points("xy")]
        if e.dxftype() == "POLYLINE" and e.is_2d_polyline:
            return [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
    except Exception:
        return None
    return None


def _is_closed(e, pts):
    try:
        if getattr(e, "closed", False) or (hasattr(e, "is_closed") and e.is_closed):
            return True
    except Exception:
        pass
    if pts and len(pts) >= 3:
        (x0, y0), (xn, yn) = pts[0], pts[-1]
        if math.hypot(x0 - xn, y0 - yn) < 1e-6:
            return True
    return False


def _shoelace_area(pts):
    if not pts or len(pts) < 3:
        return 0.0
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _perim(pts):
    if not pts or len(pts) < 2:
        return 0.0
    p = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        p += math.hypot(x2 - x1, y2 - y1)
    return p


_INSUNITS = {
    0: "unitless (SCALE UNKNOWN — red flag)", 1: "inches", 2: "feet",
    4: "mm", 5: "cm", 6: "m", 8: "microinches", 9: "mils", 10: "yards",
}


def inspect(path):
    name = os.path.basename(path)
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        print(f"\n### {name}\n  !! could not read: {e}")
        return {"name": name, "error": str(e)}
    msp = doc.modelspace()

    ins = doc.header.get("$INSUNITS", 0)
    types = Counter(e.dxftype() for e in msp)
    layers = sorted({e.dxf.layer for e in msp if e.dxf.hasattr("layer")})

    # closed polylines + areas
    closed_polys = []
    for e in msp:
        if e.dxftype() in ("LWPOLYLINE", "POLYLINE"):
            pts = _poly_points(e)
            if pts and _is_closed(e, pts):
                closed_polys.append((e.dxf.layer, pts, _shoelace_area(pts), _perim(pts)))
    n_circle = types.get("CIRCLE", 0)
    n_text = types.get("TEXT", 0) + types.get("MTEXT", 0)

    # outer contour = largest-area closed poly; the rest are interior loops (hole candidates)
    outer = max(closed_polys, key=lambda t: t[2]) if closed_polys else None
    interior = [c for c in closed_polys if c is not outer]

    # overall bbox (all entities) via ezdxf
    try:
        b = bbox.extents(msp)
        bx = (b.size.x, b.size.y) if b.has_data else (None, None)
    except Exception:
        bx = (None, None)

    # what the CURRENT heuristic does vs a real polygon:
    #   internal_cut_DERIVED = total_closed_perim - outer_perim   (overshoots on complex profiles)
    #   internal_cut_TRUE    = sum(interior loop perimeters)      (shapely-style truth)
    total_closed_perim = sum(c[3] for c in closed_polys)
    outer_perim = outer[3] if outer else 0.0
    derived_internal = max(0.0, total_closed_perim - outer_perim)
    true_internal = sum(c[3] for c in interior)
    net_area = (outer[2] - sum(c[2] for c in interior)) if outer else 0.0

    print(f"\n### {name}")
    print(f"  $INSUNITS      : {ins}  ({_INSUNITS.get(ins, '??')})")
    print(f"  entities       : " + ", ".join(f"{k}:{v}" for k, v in types.most_common()))
    print(f"  layers ({len(layers)}) : {layers}")
    print(f"  TEXT/MTEXT     : {n_text}   (0 => geometry-only, as expected)")
    print(f"  circles        : {n_circle}   (bolt/pilot holes candidates)")
    print(f"  closed polys   : {len(closed_polys)}  (1 outer + {len(interior)} interior loop(s))")
    if bx[0] is not None:
        print(f"  bbox (all)     : {bx[0]:.1f} x {bx[1]:.1f}")
    if outer:
        print(f"  outer contour  : area={outer[2]:.1f}  perim={outer_perim:.1f}  (layer '{outer[0]}')")
        print(f"  NET area       : {net_area:.1f}  (outer - interior loops; shapely would confirm)")
        print(f"  internal-cut   : DERIVED(cut-bbox-style)={derived_internal:.1f}  vs  "
              f"TRUE(sum interior)={true_internal:.1f}  "
              f"-> {'DIVERGES' if abs(derived_internal - true_internal) > 1.0 else 'agree'}")
    else:
        print(f"  !! no closed outer contour found — profile may be open lines/arcs or SPLINEs; "
              f"blank size + area NOT reliable here (abstain / flag).")
    if types.get("SPLINE"):
        print(f"  NOTE: {types['SPLINE']} SPLINE(s) present — shoelace on control points is WRONG; "
              f"shapely needs flattened splines (a real extraction concern).")
    return {
        "name": name, "insunits": ins, "n_text": n_text, "n_circle": n_circle,
        "closed": len(closed_polys), "has_outer": outer is not None,
        "derived_internal": derived_internal, "true_internal": true_internal,
        "diverges": abs(derived_internal - true_internal) > 1.0,
        "splines": types.get("SPLINE", 0),
    }


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    roots = sys.argv[1:]
    files = []
    for r in roots:
        files.extend(_find_dxfs(r))
    # de-dup preserving order
    seen = set(); uniq = []
    for f in files:
        if f not in seen:
            seen.add(f); uniq.append(f)
    files = uniq

    print("=" * 78)
    print(f"DXF INSPECTOR (read-only)   files found: {len(files)}")
    print("=" * 78)
    if not files:
        print("No .dxf files found under:", roots)
        sys.exit(0)

    results = [inspect(f) for f in files]

    ok = [r for r in results if not r.get("error")]
    print("\n" + "=" * 78)
    print("AGGREGATE")
    print("=" * 78)
    print(f"  DXFs read OK           : {len(ok)}/{len(results)}")
    unitless = [r['name'] for r in ok if r.get('insunits') == 0]
    print(f"  UNITLESS ($INSUNITS=0) : {len(unitless)}  "
          + (f"-> SCALE UNKNOWN on: {unitless}" if unitless else "(all have units — good)"))
    no_outer = [r['name'] for r in ok if not r.get('has_outer')]
    print(f"  no closed outer contour: {len(no_outer)}  "
          + (f"-> geometry unreliable on: {no_outer}" if no_outer else "(all have an outer contour)"))
    diverge = [r['name'] for r in ok if r.get('diverges')]
    print(f"  internal-cut DIVERGES  : {len(diverge)}/{len(ok)}  (current heuristic vs true)")
    if diverge:
        print(f"     -> shapely would change laser time on: {diverge}")
    have_text = [r['name'] for r in ok if r.get('n_text', 0) > 0]
    print(f"  DXFs with any TEXT     : {len(have_text)}  "
          + (f"{have_text}" if have_text else "(all geometry-only, as the model assumes)"))
    splines = [r['name'] for r in ok if r.get('splines', 0) > 0]
    if splines:
        print(f"  SPLINE present         : {splines}  (needs flattening before area/length is valid)")
    print("\nRead-only. Nothing was written. Use these facts to decide where shapely helps.")


if __name__ == "__main__":
    main()
