#!/usr/bin/env python3
r"""
_probe_dxf_dimensions.py  —  READ-ONLY.

The real part size (668 x 200) is written next to the part as DIMENSION annotations
(standard dimension lines + text), readable by eye. The DXF has 3 DIMENSION entities
plus MTEXT. This probe reads what those dimensions actually SAY — their measured
values and text — because THAT is the reliable stated size, not the scattered cut
geometry (which we showed spans the whole drawing sheet).

For each DIMENSION entity it prints:
  - dimtype, the measured value (dxf.actual_measurement if present)
  - the dimension TEXT (dxf.text — often '<>' meaning 'use measured', or an override)
  - the geometry points (defpoints) so we can see WHAT it measures and its span
  - the block it references (dimensions render via an anonymous block; the text is there)

Also dumps MTEXT/TEXT strings (the numbers may be plain text near the part), and any
numeric-looking tokens, so we can see 668 / 200 wherever they live.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_dxf_dimensions.py ^
   "\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\12532-03RecipeCard\12532-04-01G_revA .dxf"
"""
import sys, re


def main(path):
    import ezdxf
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()

    print("=" * 84)
    print("DXF DIMENSION / TEXT PROBE — 12532-04-01G  (find the stated 668 x 200)")
    print("=" * 84)

    dims = [e for e in msp if e.dxftype() == "DIMENSION"]
    print(f"\n{len(dims)} DIMENSION entities:")
    for i, d in enumerate(dims):
        print(f"\n  DIM #{i}")
        for attr in ("dimtype", "actual_measurement", "text", "dimstyle"):
            try:
                v = getattr(d.dxf, attr)
                print(f"    {attr:<20} = {v!r}")
            except Exception:
                pass
        # defpoints show the measured span
        for attr in ("defpoint", "defpoint2", "defpoint3", "text_midpoint"):
            try:
                p = getattr(d.dxf, attr)
                print(f"    {attr:<20} = ({p[0]:.1f}, {p[1]:.1f})")
            except Exception:
                pass
        # the dimension's render block holds the actual text
        try:
            blk = d.dxf.geometry  # anonymous block name *D...
            print(f"    geometry_block       = {blk!r}")
            if blk and blk in doc.blocks:
                texts = []
                for be in doc.blocks[blk]:
                    if be.dxftype() in ("TEXT", "MTEXT"):
                        t = be.dxf.text if be.dxftype() == "TEXT" else be.text
                        texts.append(t)
                if texts:
                    print(f"    block text           = {texts}")
        except Exception as e:
            pass

    # MTEXT / TEXT — the numbers may be plain annotation
    print("\n\nMTEXT / TEXT strings containing digits (looking for 668 / 200 / sizes):")
    texts = []
    for e in msp:
        if e.dxftype() == "MTEXT":
            texts.append(("MTEXT", e.text, e.dxf.insert))
        elif e.dxftype() == "TEXT":
            texts.append(("TEXT", e.dxf.text, e.dxf.insert))
    for typ, t, ins in texts:
        clean = re.sub(r"\\[A-Za-z][^;]*;", "", str(t))  # strip mtext formatting codes
        if re.search(r"\d", clean):
            nums = re.findall(r"\d+\.?\d*", clean)
            print(f"  {typ} @({ins[0]:.0f},{ins[1]:.0f}): {clean.strip()[:60]!r}  nums={nums}")

    # collect all numbers that look like plausible part dimensions (50..3000)
    print("\nALL plausible dimension-sized numbers found (50..3000mm):")
    found = set()
    for d in dims:
        try:
            m = d.dxf.actual_measurement
            if m and 50 <= m <= 3000:
                found.add(round(m, 1))
        except Exception:
            pass
    for typ, t, ins in texts:
        for n in re.findall(r"\d+\.?\d*", str(t)):
            try:
                v = float(n)
                if 50 <= v <= 3000:
                    found.add(v)
            except Exception:
                pass
    print(f"  {sorted(found)}")
    print("\n" + "=" * 84)
    print("If 668 and 200 (or ~) appear here, the stated size IS in the DXF dimensions/text")
    print("-> fix = read blank size from DIMENSION measurements, not geometry extents.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_dxf_dimensions.py <dxf path>"); sys.exit(1)
    main(sys.argv[1])
