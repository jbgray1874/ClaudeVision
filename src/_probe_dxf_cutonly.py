#!/usr/bin/env python3
r"""
_probe_dxf_cutonly.py  —  READ-ONLY.

12532-04-01G's DXF gives overall extents 2100 x 1372, but the real part (per the
drawing callout) is ~668 x 200. The probe of layers showed a wide-but-short strip
(layer '0' = 2100 x 299) that is almost certainly the base-of-drawing NOTES/TEXT,
plus SW_NOTE_* / SW_TABLEANNOTATION INSERT blocks, MTEXT, DIMENSION entities — all
ANNOTATION, not cut geometry.

Hypothesis: blank extraction took the extents of EVERYTHING (part + annotation strip).
If we compute extents from CUT geometry ONLY — LINE, SPLINE, ARC, CIRCLE, LWPOLYLINE —
and EXCLUDE MTEXT, DIMENSION, INSERT, HATCH, TEXT — do we recover ~668 x 200?

This probe:
  1. Computes bounds using ONLY cut-entity types.
  2. Computes bounds EXCLUDING known annotation layers / SW_* inserts.
  3. Shows the tightest cluster of cut geometry (to find the real part outline even if
     stray cut lines exist elsewhere).
  4. Reports per-entity-type bounds so we can see which type is inflating the box.

If cut-only bounds ~= 668 x 200, the fix is: extract blank from cut entities only,
ignoring annotation. If cut-only is STILL ~2100 wide, the part geometry itself spans
that width (stray construction lines) and the fix is harder — we'd need the drawing's
stated dimension instead.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_dxf_cutonly.py ^
   "\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\12532-03RecipeCard\12532-04-01G_revA .dxf"
"""
import sys, math

CUT_TYPES = {"LINE", "SPLINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "ELLIPSE"}
ANNO_TYPES = {"MTEXT", "TEXT", "DIMENSION", "INSERT", "HATCH", "LEADER", "MLEADER"}


def ent_points(e):
    dt = e.dxftype()
    pts = []
    try:
        if dt == "LINE":
            pts = [e.dxf.start, e.dxf.end]
        elif dt == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in e.get_points()]
        elif dt == "POLYLINE":
            pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]
        elif dt == "CIRCLE":
            c = e.dxf.center; r = e.dxf.radius
            pts = [(c[0]-r, c[1]-r), (c[0]+r, c[1]+r)]
        elif dt == "ARC":
            c = e.dxf.center; r = e.dxf.radius
            pts = [(c[0]-r, c[1]-r), (c[0]+r, c[1]+r)]
        elif dt == "ELLIPSE":
            c = e.dxf.center
            pts = [(c[0], c[1])]
        elif dt == "SPLINE":
            try:
                pts = [(p[0], p[1]) for p in e.control_points]
            except Exception:
                try:
                    pts = [(p[0], p[1]) for p in e.fit_points]
                except Exception:
                    pts = []
    except Exception:
        pts = []
    return pts


def bounds(entities):
    xmin = ymin = math.inf; xmax = ymax = -math.inf; n = 0
    for e in entities:
        for p in ent_points(e):
            x, y = p[0], p[1]
            xmin = min(xmin, x); ymin = min(ymin, y)
            xmax = max(xmax, x); ymax = max(ymax, y); n += 1
    if n == 0:
        return None
    return (xmin, ymin, xmax, ymax, xmax-xmin, ymax-ymin, n)


def main(path):
    import ezdxf
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    print("=" * 84)
    print("DXF CUT-ONLY BOUNDS PROBE — 12532-04-01G")
    print("=" * 84)

    all_ents = list(msp)
    cut = [e for e in all_ents if e.dxftype() in CUT_TYPES]
    anno = [e for e in all_ents if e.dxftype() in ANNO_TYPES]

    ba = bounds(all_ents)
    bc = bounds(cut)
    print(f"\nALL entities      : W={ba[4]:.1f} x H={ba[5]:.1f}   (engine used ~2106x1378)" if ba else "ALL: none")
    print(f"CUT geometry only : W={bc[4]:.1f} x H={bc[5]:.1f}   <-- does this ~= 668x200?" if bc else "CUT: none")

    # per cut-type bounds
    print("\nPer CUT-type bounds (which type spans the width?):")
    for t in sorted(CUT_TYPES):
        ents = [e for e in cut if e.dxftype() == t]
        b = bounds(ents)
        if b:
            print(f"  {t:<12} {len(ents):>3} ents  W={b[4]:.1f} x H={b[5]:.1f}  "
                  f"X[{b[0]:.0f}..{b[2]:.0f}] Y[{b[1]:.0f}..{b[3]:.0f}]")

    # cut geometry per layer
    print("\nCUT geometry per LAYER:")
    bylayer = {}
    for e in cut:
        bylayer.setdefault(e.dxf.layer, []).append(e)
    for lname, ents in sorted(bylayer.items(), key=lambda kv: -len(kv[1])):
        b = bounds(ents)
        if b:
            print(f"  layer {lname!r:<20} {len(ents):>3} cut ents  W={b[4]:.1f} x H={b[5]:.1f}")

    # find the densest cluster: exclude cut entities far from the median centre
    print("\nTIGHTEST cut cluster (drop outliers >2x median distance from centre):")
    centres = []
    for e in cut:
        pts = ent_points(e)
        if pts:
            cx = sum(p[0] for p in pts)/len(pts); cy = sum(p[1] for p in pts)/len(pts)
            centres.append((e, cx, cy))
    if centres:
        mx = sorted(c[1] for c in centres)[len(centres)//2]
        my = sorted(c[2] for c in centres)[len(centres)//2]
        dists = sorted(math.hypot(c[1]-mx, c[2]-my) for c in centres)
        med_d = dists[len(dists)//2] or 1
        keep = [c[0] for c in centres if math.hypot(c[1]-mx, c[2]-my) <= 3*med_d]
        b = bounds(keep)
        if b:
            print(f"  kept {len(keep)}/{len(cut)} cut ents  W={b[4]:.1f} x H={b[5]:.1f}")
            print("  (if this ~= 668x200, the real part clusters here and stray lines inflate the rest)")

    print("\n" + "=" * 84)
    print("If CUT-only or TIGHTEST ~= 668x200 -> fix = extract blank from cut geometry,")
    print("excluding annotation (MTEXT/DIMENSION/INSERT/HATCH). If still ~2100 wide,")
    print("the cut geometry itself spans it -> prefer the drawing's STATED dimension.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_dxf_cutonly.py <dxf path>"); sys.exit(1)
    main(sys.argv[1])
