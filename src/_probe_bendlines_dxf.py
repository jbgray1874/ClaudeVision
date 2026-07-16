#!/usr/bin/env python3
r"""
_probe_bendlines_dxf.py  —  READ-ONLY.

FINDING (1303A): the DXF yields estimated_bend_line_count = 0, yet the drawing plainly
shows SEVEN bends ("DOWN 90.00° R 1" x4, "UP 90.00° R 1" x2, "DOWN 78.00° R 0.10").
Tim charges £1.56 for fold; the engine model under-reads it (£0.84) because it cannot
see the bends. By contrast job 1304's DXF DID expose bends (count = 2).

QUESTION: why does one DXF expose bend lines and the other not? Almost certainly the
export settings differ (layer names, linetype, entity types). The reader keys on
dashed/长-axis lines and/or a BENDLINES-type layer.

This probe dumps, for BOTH DXFs side by side:
  - every LAYER name + entity count on it
  - entity types present (LINE / LWPOLYLINE / ARC / CIRCLE / INSERT / TEXT / DIMENSION)
  - linetypes in use (CONTINUOUS / DASHED / HIDDEN / CENTER ...)
  - which layers look like bend/fold layers by name
  - counts of dashed lines (the signal the reader uses)

OUTPUT lets us tell Design EXACTLY what to change: e.g. "export bend lines on a layer
named BENDLINES with a DASHED linetype", rather than a vague 'be consistent'.

Requires ezdxf (the engine already uses it).

Usage (run from C:\ClaudeVision\src):
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_bendlines_dxf.py
"""
import sys
from collections import Counter

try:
    import ezdxf
except ImportError:
    sys.exit("ezdxf not available in this venv — is the engine's DXF reader using something else?")

DXFS = {
    "1303A (0 bends detected — PROBLEM)":
        r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1303A-CircSawShelf\1303A-01_1.2mm MS_RevB.DXF",
    "1304   (2 bends detected — WORKS)":
        r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1304-01GrinderHolder\1304-01_1.5mm MS_RevF.DXF",
}

BEND_HINTS = ("BEND", "FOLD", "CREASE", "FORM", "UP", "DOWN")


def analyse(label, path):
    print("\n" + "=" * 96)
    print(label)
    print(path)
    print("=" * 96)
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        print(f"  !! could not read: {e}")
        return
    msp = doc.modelspace()

    layer_counts = Counter()
    layer_types = {}
    type_counts = Counter()
    linetype_counts = Counter()
    dashed_lines = 0
    layer_linetypes = {}

    for e in msp:
        lay = str(e.dxf.layer)
        et = e.dxftype()
        layer_counts[lay] += 1
        type_counts[et] += 1
        layer_types.setdefault(lay, Counter())[et] += 1
        lt = str(getattr(e.dxf, "linetype", "BYLAYER"))
        linetype_counts[lt] += 1
        layer_linetypes.setdefault(lay, Counter())[lt] += 1

    # layer table linetypes (BYLAYER resolves here)
    print("\n-- LAYER TABLE (name -> linetype, colour) --")
    for lyr in doc.layers:
        print(f"   {lyr.dxf.name:<28} linetype={str(lyr.dxf.linetype):<14} colour={lyr.dxf.color}")

    print("\n-- ENTITIES PER LAYER --")
    for lay, n in layer_counts.most_common():
        types = ", ".join(f"{t}×{c}" for t, c in layer_types[lay].most_common())
        lts = ", ".join(f"{t}×{c}" for t, c in layer_linetypes[lay].most_common())
        flag = ""
        if any(h in lay.upper() for h in BEND_HINTS):
            flag = "   <<< looks like a BEND/FOLD layer"
        print(f"   {lay:<28} n={n:<5} [{types}]")
        print(f"   {'':<28} linetypes: {lts}{flag}")

    print("\n-- ENTITY TYPES (all) --")
    for t, c in type_counts.most_common():
        print(f"   {t:<16} {c}")

    print("\n-- LINETYPES IN USE (entity-level) --")
    for t, c in linetype_counts.most_common():
        print(f"   {t:<16} {c}")

    # resolve dashed: entity linetype, or BYLAYER -> layer's linetype
    layer_lt = {l.dxf.name: str(l.dxf.linetype).upper() for l in doc.layers}
    dashed = 0
    for e in msp:
        lt = str(getattr(e.dxf, "linetype", "BYLAYER")).upper()
        if lt == "BYLAYER":
            lt = layer_lt.get(str(e.dxf.layer), "CONTINUOUS")
        if "DASH" in lt or "HIDDEN" in lt or "CENTER" in lt:
            dashed += 1
    print(f"\n-- DASHED/HIDDEN/CENTER entities (resolved through BYLAYER): {dashed}")
    print("   (this is the kind of signal a bend-line reader keys on)")


def main():
    print("BEND-LINE DXF COMPARISON PROBE (read-only)")
    print("Why does 1304's DXF expose bend lines but 1303A's does not?")
    for label, path in DXFS.items():
        analyse(label, path)
    print("\n" + "=" * 96)
    print("READ: compare the two. Look for —")
    print("  * a layer in 1304 whose name/linetype marks bends, ABSENT in 1303A")
    print("  * dashed/hidden linetypes present in 1304 but not 1303A")
    print("  * bends drawn as plain CONTINUOUS lines in 1303A (indistinguishable from cuts)")
    print("That difference is the concrete instruction to give Design.")


if __name__ == "__main__":
    main()
