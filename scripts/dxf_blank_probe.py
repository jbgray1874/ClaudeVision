"""
dxf_blank_probe.py — why does the DXF blank differ from the model's flat pattern?

Written for the 12120 finding: every DXF blank measures exactly 6.00 mm larger than the
SolidWorks cut-list flat, on BOTH axes, on all seven parts — including parts with no bends
at all, so no bend allowance can explain it. Two possibilities, needing opposite fixes:

  (a) something OTHER than the cut profile sits on the layers the reader treats as cut
      geometry (a bounding-box rectangle from the DXF export options, an etch line, a
      lead-in, a border). Then the DXF is fine and OUR READER is inflating the blank.
  (b) the cut profile itself is 3 mm out all round. Then the file is what it is, and the
      question is one for the drawing office: deliberate cutting allowance, or an
      oversized export.

Guessing between those from export settings is backwards. This reads the file and reports,
per LAYER, the entity counts and extents — so whichever it is, it is visible rather than
argued. It measures and prints; it changes nothing.

Usage:
    python scripts/dxf_blank_probe.py <file.dxf|folder> [--expect LxW] [--extract <sw.json>]

    --expect 126.39x82.2   compare against a known flat
    --extract <path>       take the expected flat per part from a SolidWorks native
                           extract, matching on the part number in the DXF filename
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

try:
    import ezdxf
except ImportError:
    print("ezdxf is required:  pip install ezdxf")
    sys.exit(2)

# The layers src/dxf_reader treats as the cut outline. Anything on these drives the blank.
CUT_LAYERS = {"SLD-0", "0", "VISIBLE EDGES(BENCHMARK)"}


def _extents(entities) -> Optional[Tuple[float, float, float, float]]:
    """(min_x, min_y, max_x, max_y) over every vertex we can reach on these entities."""
    xs: List[float] = []
    ys: List[float] = []
    for e in entities:
        t = e.dxftype()
        try:
            if t == "LINE":
                xs += [e.dxf.start.x, e.dxf.end.x]
                ys += [e.dxf.start.y, e.dxf.end.y]
            elif t in ("CIRCLE", "ARC"):
                # Full extent of the circle/arc envelope — an arc's true extent needs its
                # angular span, so this is an UPPER bound and is labelled as such below.
                c, r = e.dxf.center, e.dxf.radius
                xs += [c.x - r, c.x + r]
                ys += [c.y - r, c.y + r]
            elif t in ("LWPOLYLINE", "POLYLINE"):
                for p in e.get_points() if t == "LWPOLYLINE" else e.points():
                    xs.append(p[0])
                    ys.append(p[1])
            elif t == "POINT":
                xs.append(e.dxf.location.x)
                ys.append(e.dxf.location.y)
        except Exception:
            continue
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def probe(path: str, expect: Optional[Tuple[float, float]] = None) -> None:
    try:
        doc = ezdxf.readfile(path)
    except Exception as exc:
        print(f"  ! could not read: {exc}")
        return
    msp = doc.modelspace()

    # EXPLODE INSERTs. src/dxf_reader collects model-space entities only and does not
    # explode blocks, so a SolidWorks export that wraps the profile in a block reads as an
    # empty cut layer. Exploding here shows what IS in the file, and the "src" column below
    # says whether the engine can currently see it — the difference between "the geometry is
    # missing" and "the geometry is there but we do not read it" needs opposite fixes.
    by_layer: Dict[str, List] = {}
    exploded_layers: set = set()
    for e in msp:
        lay = str(getattr(e.dxf, "layer", "") or "").upper()
        if e.dxftype() == "INSERT":
            try:
                kids = list(e.virtual_entities())
            except Exception:
                kids = []
            if kids:
                for k in kids:
                    klay = str(getattr(k.dxf, "layer", "") or "").upper() or lay
                    by_layer.setdefault(klay, []).append(k)
                    exploded_layers.add(klay)
                continue
        by_layer.setdefault(lay, []).append(e)

    print(f"  layers: {len(by_layer)}")
    header = f"    {'layer':<28} {'ents':>5}  {'extent (mm)':<26} {'size (mm)':<20} cut?"
    print(header)
    print("    " + "-" * (len(header) - 4))
    for layer in sorted(by_layer):
        ents = by_layer[layer]
        ext = _extents(ents)
        is_cut = "CUT" if layer in CUT_LAYERS else ""
        if layer in exploded_layers:
            is_cut = (is_cut + " (from INSERT - engine does NOT read these)").strip()
        if not ext:
            print(f"    {layer:<28} {len(ents):>5}  {'(no vertices)':<26} {'':<20} {is_cut}")
            continue
        w, h = ext[2] - ext[0], ext[3] - ext[1]
        span = f"{ext[0]:.2f},{ext[1]:.2f} .. {ext[2]:.2f},{ext[3]:.2f}"
        print(f"    {layer:<28} {len(ents):>5}  {span:<26} {w:>8.2f} x {h:<8.2f} {is_cut}")

    # What the engine would measure: the union of the cut layers.
    cut_ents = [e for lay, es in by_layer.items() if lay in CUT_LAYERS for e in es]
    ext = _extents(cut_ents)
    if not ext:
        print("    -> no entities on any cut layer")
        return
    w, h = ext[2] - ext[0], ext[3] - ext[1]
    print(f"    => blank the engine reads (cut layers): {w:.2f} x {h:.2f} mm")

    if expect:
        el, ew = max(expect), min(expect)
        al, aw = max(w, h), min(w, h)
        dl, dw = al - el, aw - ew
        print(f"    => model flat:                          {el:.2f} x {ew:.2f} mm")
        print(f"    => DIFFERENCE:                          {dl:+.2f} x {dw:+.2f} mm")
        if abs(dl) > 0.05 or abs(dw) > 0.05:
            # Is any single cut-layer entity responsible for the overshoot? If the profile
            # alone matches the model, the extra is a separate entity and the reader is at
            # fault; if every entity is inside the profile, the profile itself is oversize.
            outer = []
            for e in cut_ents:
                ee = _extents([e])
                if not ee:
                    continue
                if (ee[0] < ext[0] + 0.05 or ee[1] < ext[1] + 0.05
                        or ee[2] > ext[2] - 0.05 or ee[3] > ext[3] - 0.05):
                    outer.append((e.dxftype(),
                                  str(getattr(e.dxf, "layer", "") or ""),
                                  f"{ee[0]:.2f},{ee[1]:.2f}..{ee[2]:.2f},{ee[3]:.2f}"))
            print(f"    -> {len(outer)} entity(ies) touch the outer extent:")
            for t, lay, span in outer[:12]:
                print(f"         {t:<12} layer={lay:<20} {span}")
            if len(outer) > 12:
                print(f"         ... and {len(outer) - 12} more")


def _expected_from_extract(extract_path: str) -> Dict[str, Tuple[float, float]]:
    """part number -> (flat_length, flat_width) from a SolidWorks native extract."""
    out: Dict[str, Tuple[float, float]] = {}
    try:
        with open(extract_path, encoding="utf-8") as fh:
            records = json.load(fh)
    except Exception as exc:
        print(f"could not read extract {extract_path}: {exc}")
        return out
    for r in records if isinstance(records, list) else []:
        rs = (r or {}).get("route_signals") or {}
        fl, fw = rs.get("flat_length_mm"), rs.get("flat_width_mm")
        if fl and fw:
            out[str(r.get("title") or "").strip().upper()] = (float(fl), float(fw))
    return out


def _match_expected(dxf_name: str, table: Dict[str, Tuple[float, float]]):
    """Match a DXF filename to a part number. Filenames carry extra tokens
    ('12120-01-01M_1.5mm MS_RevG.DXF'), so the longest part number contained in the
    name wins — longest so '12120-01-01M' beats a shorter prefix."""
    up = dxf_name.upper()
    hits = [pn for pn in table if pn and pn in up]
    return table[max(hits, key=len)] if hits else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="a .dxf file, or a folder to scan")
    ap.add_argument("--expect", help="expected flat as LxW, e.g. 126.39x82.2")
    ap.add_argument("--extract", help="SolidWorks native extract JSON for per-part expectations")
    args = ap.parse_args()

    expect_one = None
    if args.expect:
        m = re.match(r"\s*([\d.]+)\s*[xX]\s*([\d.]+)\s*$", args.expect)
        if not m:
            print("--expect must look like 126.39x82.2")
            sys.exit(2)
        expect_one = (float(m.group(1)), float(m.group(2)))

    table = _expected_from_extract(args.extract) if args.extract else {}
    if table:
        print(f"expected flats loaded for {len(table)} part(s) from the SolidWorks extract\n")

    if os.path.isdir(args.path):
        files = [os.path.join(args.path, f) for f in sorted(os.listdir(args.path))
                 if f.lower().endswith(".dxf")]
    else:
        files = [args.path]
    if not files:
        print(f"no .dxf found in {args.path}")
        sys.exit(1)

    for f in files:
        print(f"=== {os.path.basename(f)}")
        exp = expect_one or (_match_expected(os.path.basename(f), table) if table else None)
        if table and not exp:
            print("  (no matching part in the extract — reporting extents only)")
        probe(f, exp)
        print()


if __name__ == "__main__":
    main()
