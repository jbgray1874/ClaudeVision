r"""
patch_dxf_shapely_netarea.py  —  replace the broken _order_segments/_shoelace_area net-area
in dxf_reader.py.py with a shapely polygonize reconstruction (outer contour minus holes),
proven on all 14 job-1282 DXFs (14/14 close, fill 83-100%; peg panel 90mm2 -> 264,527mm2).

SURGICAL: only the net-area computation changes. perimeter_mm, bbox_area_mm2,
blank_length_mm, blank_width_mm are preserved BYTE-IDENTICAL. Abstain gate falls back to
bbox (flagged) if a profile can't be reconstructed, so a bad export never poisons the
estimate — and because live costing reads L x W (not blank_area_mm2) today, this is a
NO-OP on the 1282 total. It only makes blank_area_mm2 correct so powder/weight can later
be switched onto true net area as a separate, measured step.

Three edits, each match-or-refuse against the LIVE bytes:
  1. INJECT  _shapely_net_area_mm2 helper just before _exact_perimeter_and_area
  2. REPLACE the "# Shoelace area" block with a call to that helper (+ area_method)
  3. THREAD  cut_circs into the _exact_perimeter_and_area call site + widen its signature
Idempotent: refuses if already patched. Makes a .bak once.
"""
import sys, shutil, ast
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\dxf_reader.py.py")

INJECT = '''def _shapely_net_area_mm2(cut_lines, cut_arcs, cut_circs, scale, bbox_area_mm2):
    """Reconstruct true net blank area (outer contour minus holes) from loose LINE+ARC
    cut geometry using shapely polygonize. Returns (area_mm2, method, fill_pct).

    Replaces _order_segments/_shoelace_area (endpoint-walk of LINES only, ignored ARCs)
    which collapsed to ~0 on curved/perforated profiles. ABSTAIN GATE: no ring, or net
    area not a sane fraction of bbox (fill 30-100%) -> return bbox flagged, never garbage.
    Falls back to bbox if shapely is unavailable. Proven on all 14 job-1282 DXFs.
    """
    try:
        from shapely.ops import polygonize, unary_union, snap as _snap
        from shapely.geometry import LineString, Point
        import math as _m
    except Exception:
        return (bbox_area_mm2, "bbox_no_shapely", 100.0)

    segs = []
    _sag = 0.20 / max(scale, 1e-9)
    for e in cut_lines:
        a = (e.dxf.start.x * scale, e.dxf.start.y * scale)
        b = (e.dxf.end.x * scale, e.dxf.end.y * scale)
        if _m.dist(a, b) > 1e-6:
            segs.append(LineString([a, b]))
    for e in cut_arcs:
        try:
            pts = [(v.x * scale, v.y * scale) for v in e.flattening(_sag)]
        except Exception:
            continue
        for i in range(len(pts) - 1):
            if _m.dist(pts[i], pts[i + 1]) > 1e-6:
                segs.append(LineString([pts[i], pts[i + 1]]))
    if not segs:
        return (bbox_area_mm2, "bbox_no_segments", 100.0)

    net = unary_union(segs)
    try:
        net = _snap(net, net, 0.05)           # weld sub-micron CAD endpoint gaps (mm)
    except Exception:
        pass
    polys = list(polygonize(unary_union(net)))
    if not polys:
        return (bbox_area_mm2, "bbox_polygonize_empty", 0.0)

    outer = max(polys, key=lambda p: p.area)
    interior = [p for p in polys if p is not outer]
    net_area = max(0.0, outer.area - sum(p.area for p in interior))

    for e in (cut_circs or []):
        try:
            r = float(getattr(e.dxf, "radius", 0.0) or 0.0) * scale
            if r < 0.5:
                continue
            c = (e.dxf.center.x * scale, e.dxf.center.y * scale)
            disc = Point(c).buffer(r, resolution=16)
            if outer.contains(disc.representative_point()):
                net_area = max(0.0, net_area - disc.area)
        except Exception:
            continue

    fill = (100.0 * net_area / bbox_area_mm2) if bbox_area_mm2 > 0 else 0.0
    if not (30.0 <= fill <= 100.5):
        return (bbox_area_mm2, "bbox_fill_out_of_band", round(fill, 1))
    return (round(net_area, 2), "shapely_polygonize", round(fill, 1))


'''

# ---- Edit 1: inject helper before the function definition ----
ANCHOR_DEF = "def _exact_perimeter_and_area(\n    cut_lines: List[Any],\n    cut_arcs:  List[Any],\n    scale: float,\n) -> Dict[str, float]:"

# ---- Edit 2: replace the shoelace block ----
OLD_BLOCK = '''    # Shoelace area
    pts  = _order_segments(cut_lines, scale=scale)
    area = _shoelace_area(pts)
    if area < 1.0 and bbox_area > 0:
        area = bbox_area          # fallback if ordering failed

    fill_pct = round(100.0 * area / bbox_area, 1) if bbox_area > 0 else 0.0'''

NEW_BLOCK = '''    # Net area via shapely polygonize (outer contour minus holes). Replaces the
    # _order_segments endpoint-walk, which ignored ARCs and collapsed to ~0 on any
    # profile with curved corners/holes (peg panel 90mm2 for a 553x525 part). Proven on
    # all 14 job-1282 DXFs: 14/14 close, fill 83-100%. Abstains to bbox (flagged) if the
    # reconstruction is implausible, so a bad export never poisons area/weight/powder.
    area, _area_method, fill_pct = _shapely_net_area_mm2(
        cut_lines, cut_arcs, cut_circs, scale, bbox_area
    )
    if area < 1.0 and bbox_area > 0:
        area = bbox_area                      # last-resort guard (function already abstains)
        _area_method = "bbox_guard"'''

# ---- Edit 3: widen signature to accept cut_circs (default None so any other caller is safe) ----
OLD_SIG = '''def _exact_perimeter_and_area(
    cut_lines: List[Any],
    cut_arcs:  List[Any],
    scale: float,
) -> Dict[str, float]:'''
NEW_SIG = '''def _exact_perimeter_and_area(
    cut_lines: List[Any],
    cut_arcs:  List[Any],
    scale: float,
    cut_circs: List[Any] = None,
) -> Dict[str, float]:'''

# ---- Edit 4: thread cut_circs at the call site in extract_flat_pattern_data ----
OLD_CALL = "    outline  = _exact_perimeter_and_area(cut_lines, cut_arcs, scale)"
NEW_CALL = "    outline  = _exact_perimeter_and_area(cut_lines, cut_arcs, scale, cut_circs)"

# ---- Edit 5: return dict gets area_method ----
OLD_RET = '''        "bbox_fill_pct":   fill_pct,
    }'''
NEW_RET = '''        "bbox_fill_pct":   fill_pct,
        "area_method":     _area_method,
    }'''

# ---- Edit 6: docstring honesty ----
OLD_DOC = '''    cut-outline layer.  Lines are ordered for the shoelace; arcs add their
    arc-length to perimeter but are not included in the polygon.'''
NEW_DOC = '''    cut-outline layer.  Net area comes from shapely polygonize (outer contour minus
    holes); arc-length is added to the perimeter (laser cut length).'''


def main():
    if not TARGET.is_file():
        sys.exit(f"NOT FOUND: {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "_shapely_net_area_mm2" in src:
        sys.exit("Already patched (found _shapely_net_area_mm2). No change made.")

    edits = [
        ("inject helper",   ANCHOR_DEF, INJECT + ANCHOR_DEF),
        ("replace shoelace block", OLD_BLOCK, NEW_BLOCK),
        ("widen signature", OLD_SIG, NEW_SIG),
        ("thread cut_circs at call site", OLD_CALL, NEW_CALL),
        ("add area_method to return", OLD_RET, NEW_RET),
        ("update docstring", OLD_DOC, NEW_DOC),
    ]
    # NOTE: OLD_SIG is a substring of ANCHOR_DEF+INJECT after edit 1, so apply signature
    # widening to the ORIGINAL sig occurrence. Order matters — do inject last on the def.
    # Re-order: signature/doc first (unique in original), then block/ret, then inject.
    ordered = [
        ("widen signature", OLD_SIG, NEW_SIG),
        ("update docstring", OLD_DOC, NEW_DOC),
        ("replace shoelace block", OLD_BLOCK, NEW_BLOCK),
        ("add area_method to return", OLD_RET, NEW_RET),
        ("thread cut_circs at call site", OLD_CALL, NEW_CALL),
        ("inject helper", NEW_SIG, INJECT + NEW_SIG),  # inject before the NOW-widened sig
    ]

    for label, old, new in ordered:
        n = src.count(old)
        if n != 1:
            sys.exit(f"REFUSE [{label}]: anchor found {n} times (expected 1). No change written.")
        src = src.replace(old, new, 1)

    # validate the whole module still parses
    try:
        ast.parse(src)
    except SyntaxError as e:
        sys.exit(f"REFUSE: patched file does not parse: {e}")

    bak = TARGET.with_suffix(TARGET.suffix + ".bak_shapely")
    if not bak.exists():
        shutil.copy2(TARGET, bak)
    TARGET.write_text(src, encoding="utf-8")
    print(f"PATCHED {TARGET}")
    print(f"  backup: {bak}")
    print("  edits: signature+cut_circs, docstring, shoelace->shapely, area_method, call-site, helper injected")
    print("  blank_length_mm / blank_width_mm / perimeter_mm / bbox_area_mm2: UNCHANGED")
    print("  NEXT: re-run flag-on 1282 — total MUST stay the same (costing reads L x W, not blank_area_mm2).")


if __name__ == "__main__":
    main()
