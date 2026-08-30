# -*- coding: utf-8 -*-
r"""DXF INSPECTION PROBE (read-only).

Dumps the raw entity reality of a DXF so we can verify the engine's geometry numbers
against the actual drawing — BEFORE changing any reader logic. Answers:
  - what scale is resolved ($INSUNITS -> mm factor)? Is it sane vs the bounding box?
  - entity-type histogram (LINE / ARC / CIRCLE / LWPOLYLINE / POLYLINE / SPLINE / DIMENSION)
  - polylines: how many CLOSED vs OPEN, and how many closed ones are "small" (counted as holes)
  - circle diameters (the real hole picture)
  - cut-length broken down BY ENTITY TYPE and BY LAYER (to see what inflates it)
  - bounding box (the part's real size — cross-check against scale)

Usage (auto-discovers 1282 DXFs, or pass a path / a folder):
  C:\ClaudeVision\.venv\Scripts\python.exe _dxf_inspect_diag.py
  C:\ClaudeVision\.venv\Scripts\python.exe _dxf_inspect_diag.py "K:\...\1449C ... RevB.DXF"
  C:\ClaudeVision\.venv\Scripts\python.exe _dxf_inspect_diag.py "K:\...\1282 - Milwaukee Wall Bay"

Read-only: opens DXFs, prints. Never writes, never touches the DB.
"""
import sys
import math
from pathlib import Path
from collections import Counter, defaultdict

try:
    import ezdxf
except Exception as e:
    print(f"ezdxf not importable: {e}")
    sys.exit(1)

# Reuse the engine's own scale table if available, so the probe sees what the reader sees.
try:
    from dxf_reader_py import insunits_to_mm_factor
except Exception:
    _INSUNITS_TO_MM = {0: 1.0, 1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0}
    def insunits_to_mm_factor(u):
        return float(_INSUNITS_TO_MM.get(int(u), 1.0))


def _dist(a, b):
    return math.hypot(float(b[0]) - float(a[0]), float(b[1]) - float(a[1]))


def _polyline_len(e, scale):
    try:
        pts = [(p[0], p[1]) for p in e.get_points()]
    except Exception:
        try:
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        except Exception:
            return 0.0
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for i in range(len(pts) - 1):
        total += _dist(pts[i], pts[i + 1])
    closed = bool(getattr(e, "closed", False))
    if closed and len(pts) > 2:
        total += _dist(pts[-1], pts[0])
    return total * scale


def inspect(dxf_path: Path):
    print("\n" + "=" * 78)
    print(f"DXF: {dxf_path.name}")
    print("=" * 78)
    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception as e:
        print(f"  FAILED to read: {e}")
        return

    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    measurement = int(doc.header.get("$MEASUREMENT", 0) or 0)
    scale = insunits_to_mm_factor(insunits)
    print(f"  $INSUNITS = {insunits}  -> scale factor = {scale} (mm per drawing unit)")
    print(f"  $MEASUREMENT = {measurement}  (0=imperial default, 1=metric)")
    print(f"  dxfversion = {doc.dxfversion}")
    if insunits == 0:
        print("  ** WARNING: INSUNITS=0 (unitless). Scale defaults to 1.0 -> read as mm.")
        print("     If the part was drawn in other units, ALL numbers are mis-scaled.")

    try:
        msp = doc.modelspace()
        entities = list(msp)
    except Exception as e:
        print(f"  cannot iterate modelspace: {e}")
        return

    type_hist = Counter()
    layer_hist = Counter()
    cut_by_type = defaultdict(float)
    cut_by_layer = defaultdict(float)
    circle_diams = []
    closed_poly = 0
    open_poly = 0
    small_closed_poly = 0       # < 80mm perimeter -> reader counts these as holes
    small_closed_poly_perims = []
    xs, ys = [], []

    for e in entities:
        t = e.dxftype()
        type_hist[t] += 1
        layer = str(getattr(e.dxf, "layer", "") or "")
        layer_hist[layer] += 1
        L = 0.0
        try:
            if t == "LINE":
                s, en = e.dxf.start, e.dxf.end
                L = _dist((s.x, s.y), (en.x, en.y)) * scale
                xs += [s.x, en.x]; ys += [s.y, en.y]
            elif t == "ARC":
                r = float(e.dxf.radius)
                ang = abs(float(e.dxf.end_angle) - float(e.dxf.start_angle))
                L = (math.radians(ang) * r) * scale
                c = e.dxf.center; xs.append(c.x); ys.append(c.y)
            elif t == "CIRCLE":
                d = float(e.dxf.radius) * 2.0 * scale
                circle_diams.append(round(d, 2))
                L = math.pi * d
                c = e.dxf.center; xs.append(c.x); ys.append(c.y)
            elif t in ("LWPOLYLINE", "POLYLINE"):
                L = _polyline_len(e, scale)
                is_closed = bool(getattr(e, "closed", False))
                if is_closed:
                    closed_poly += 1
                    if L < 80.0:
                        small_closed_poly += 1
                        small_closed_poly_perims.append(round(L, 1))
                else:
                    open_poly += 1
                try:
                    for p in e.get_points():
                        xs.append(p[0]); ys.append(p[1])
                except Exception:
                    pass
            elif t == "SPLINE":
                try:
                    L = float(e.length()) * scale
                except Exception:
                    L = 0.0
        except Exception:
            pass
        if L > 0.05:
            cut_by_type[t] += L
            cut_by_layer[layer] += L

    print(f"\n  Total entities: {len(entities)}")
    print("  Entity histogram:")
    for t, n in type_hist.most_common():
        print(f"    {t:14} {n}")

    print(f"\n  Polylines: closed={closed_poly}, open={open_poly}, "
          f"small-closed(<80mm, counted as holes)={small_closed_poly}")
    if small_closed_poly_perims:
        print(f"    small-closed perimeters (mm): {sorted(set(small_closed_poly_perims))[:20]}")

    print(f"\n  CIRCLE count = {len(circle_diams)}")
    if circle_diams:
        dc = Counter(circle_diams)
        print("  Circle diameters (mm) -> count:")
        for d, n in sorted(dc.items()):
            print(f"    {d:8} mm  x {n}")

    # The reader's hole logic: estimated_hole_count = max(circle_count, len(set(diams)+small closed))
    reader_holes = max(len(circle_diams), len(set(circle_diams)) + 0)
    reader_pierces = reader_holes + closed_poly
    print(f"\n  >> Reader would estimate: holes ~ max(circles={len(circle_diams)}, "
          f"unique-diam={len(set(circle_diams))}) ; pierces = holes + closed_poly({closed_poly})")
    print(f"     NOTE: small closed polylines ({small_closed_poly}) ALSO feed hole_diameters -> "
          f"possible double-count vs circles")

    total_cut = sum(cut_by_type.values())
    print(f"\n  Cut-length total = {total_cut:.1f} mm")
    print("  Cut-length BY ENTITY TYPE:")
    for t, v in sorted(cut_by_type.items(), key=lambda kv: -kv[1]):
        print(f"    {t:14} {v:10.1f} mm  ({100*v/total_cut:4.1f}%)")
    print("  Cut-length BY LAYER (top 12) — annotation/dimension layers here = inflation:")
    for lyr, v in sorted(cut_by_layer.items(), key=lambda kv: -kv[1])[:12]:
        print(f"    {lyr[:28]:28} {v:10.1f} mm  ({100*v/total_cut:4.1f}%)")

    if xs and ys:
        bb_w = (max(xs) - min(xs)) * scale
        bb_h = (max(ys) - min(ys)) * scale
        print(f"\n  Bounding box (scaled) ~ {bb_w:.1f} x {bb_h:.1f} mm")
        print("  ^ cross-check against the part's real size on the drawing. If wildly off")
        print("    (e.g. 25x or 1000x), the INSUNITS scale is wrong.")


def _dedupe(paths):
    seen = set(); uniq = []
    for p in paths:
        k = str(p).lower()
        if k not in seen:
            seen.add(k); uniq.append(p)
    return uniq


def discover(arg):
    # If a path/folder is given, honour it exactly (single DXF, or a SPECIFIC folder).
    if arg:
        p = Path(arg)
        if p.is_dir():
            return _dedupe(sorted(p.rglob("*.DXF")) + sorted(p.rglob("*.dxf")))
        return [p]

    # No arg: scope STRICTLY to the two agreed jobs (1282 + 12479). We deliberately do NOT
    # rglob C:\ClaudeVision\input or the cwd — that swept up every DXF in the tree (the
    # over-pull). Only the named job folders are searched.
    job_roots = [
        Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay"),
        Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\12479 - Replen Trolley"),
        # fallbacks in case the live-enquiry folders aren't reachable from this machine:
        Path(r"C:\ClaudeVision\input\1282 - Milwaukee Wall Bay"),
        Path(r"C:\ClaudeVision\input\12479 - Replen Trolley"),
    ]
    paths = []
    found_roots = []
    for r in job_roots:
        if r.exists():
            hits = sorted(r.rglob("*.DXF")) + sorted(r.rglob("*.dxf"))
            if hits:
                found_roots.append((r, len(hits)))
                paths += hits
    paths = _dedupe(paths)
    if found_roots:
        print("Scoped to job folders:")
        for r, n in found_roots:
            print(f"   {r}  ({n} DXF)")
    return paths


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    targets = discover(arg)
    if not targets:
        print("No DXFs found in the 1282 / 12479 job folders.")
        print("Pass an explicit DXF or a specific folder if they live elsewhere:")
        print(r'  python _dxf_inspect_diag.py "K:\...\1449C - 50cm Peg Metal Panel MS_1mm_RevB.DXF"')
        print(r'  python _dxf_inspect_diag.py "K:\...\Live Enquiry\12479 - Replen Trolley"')
        sys.exit(0)

    # Safety cap: this probe is meant for ONE job (≤ ~20 DXFs). If discovery returns far more,
    # something is mis-scoped — list them and stop rather than dumping hundreds of inspections.
    CAP = 30
    if len(targets) > CAP:
        print(f"\n** {len(targets)} DXFs found — that's more than one job's worth (cap {CAP}).")
        print("   Refusing to dump all of them. The paths found were:")
        for t in targets[:60]:
            print(f"     {t}")
        print("   Pass a SINGLE job folder or a specific DXF to scope this down.")
        sys.exit(0)

    print(f"\nInspecting {len(targets)} DXF(s) (priority: peg panels, then simple parts)...")
    def _prio(p):
        n = p.name.upper()
        if "PEG" in n: return 0           # 1449 / 2621 — the 386-hole question
        if "FOOTBASE" in n or "3886" in n: return 1   # simple known parts
        return 2
    for t in sorted(targets, key=_prio):
        inspect(t)
