#!/usr/bin/env python3
r"""
_probe_dxf_weld.py  —  READ-ONLY. Reads a DXF, writes nothing.

Purpose: evidence whether a part could involve welding. A single flat-pattern
laser blank (one outer profile + internal cut-outs/holes, all on the cut layer)
has NO weld. Welding only exists between multiple parts / bodies. This reports
the entity mix, layer names, how many closed loops (bodies) exist, and whether
anything looks like a weld/assembly annotation.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_dxf_weld.py ^
    "K:\Estimating\Completed\AI Estimating\Live Enquiry\1300-01FlatShelf\1300-01 MS_1.2mm REVF.DXF"

Needs ezdxf (the engine already uses it). Falls back to a raw text scan if ezdxf
can't open the file, so it still tells you something.
"""
import sys, os, collections


def raw_scan(path):
    print("[raw text scan fallback]")
    txt = open(path, "r", errors="ignore").read()
    up = txt.upper()
    for kw in ("WELD", "SPOTWELD", "SPOT WELD", "MIG", "TIG", "CO2", "TACK", "ASSEMBLY", "ASSEMBLE"):
        print(f"   keyword {kw!r:12}: {up.count(kw)} occurrence(s)")
    # crude entity tag counts
    for tag in ("LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC", "SPLINE", "TEXT", "MTEXT", "INSERT"):
        print(f"   entity {tag:12}: {up.count(chr(10)+tag)}")


def main(path):
    if not os.path.exists(path):
        print("FILE NOT FOUND:", path); return
    print("=" * 74)
    print("DXF WELD / BODY PROBE  (read-only)")
    print("file:", path)
    print("=" * 74)
    try:
        import ezdxf
    except ImportError:
        print("ezdxf not importable — using raw scan.\n"); raw_scan(path); return
    try:
        doc = ezdxf.readfile(path)
    except Exception as e:
        print(f"ezdxf could not open ({e}) — using raw scan.\n"); raw_scan(path); return

    msp = doc.modelspace()
    etypes = collections.Counter()
    layers = collections.Counter()
    texts = []
    closed_loops = 0
    inserts = 0
    for e in msp:
        t = e.dxftype()
        etypes[t] += 1
        try:
            layers[e.dxf.layer] += 1
        except Exception:
            pass
        if t in ("LWPOLYLINE", "POLYLINE"):
            try:
                if getattr(e, "closed", False) or getattr(e.dxf, "flags", 0) & 1:
                    closed_loops += 1
            except Exception:
                pass
        if t in ("TEXT", "MTEXT"):
            try:
                texts.append((e.dxf.text if t == "TEXT" else e.text).strip())
            except Exception:
                pass
        if t == "INSERT":
            inserts += 1

    print("\nENTITY TYPES:")
    for k, v in etypes.most_common():
        print(f"   {k:14}: {v}")
    print("\nLAYERS:")
    for k, v in layers.most_common():
        print(f"   {k:20}: {v} entities")
    print(f"\nclosed polyline loops (candidate bodies/holes): {closed_loops}")
    print(f"block INSERTs (sub-parts):                      {inserts}")

    weldish = [x for x in texts if any(w in x.upper()
               for w in ("WELD", "SPOT", "MIG", "TIG", "TACK", "ASSEMBLY", "ASSEMBLE", "CO2"))]
    print("\nTEXT/annotations that mention weld/assembly:")
    print("   " + ("NONE FOUND" if not weldish else " | ".join(weldish[:20])))

    print("\n" + "-" * 74)
    verdict_no_weld = (inserts == 0) and (not weldish)
    print("VERDICT:")
    if verdict_no_weld:
        print("   Single flat-pattern blank: one part, no block inserts, no weld/assembly")
        print("   annotations. -> NO WELD is present in this DXF. The engine's Weld (CO2)")
        print("   line is phantom and safe to suppress for this part.")
    else:
        print("   Found INSERTs or weld/assembly annotations -> DO NOT assume no weld;")
        print("   inspect before suppressing. Details above.")
    print("=" * 74)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(r'usage: python _probe_dxf_weld.py "<path to .DXF>"'); sys.exit(1)
    main(sys.argv[1])
