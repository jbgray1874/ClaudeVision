# -*- coding: utf-8 -*-
r"""Diagnose JR's 'dimensions slightly off' on 1282. Read-only.
For each base-plate / header DXF: show chosen file, raw bbox, scale, final mm, AND the
cut-length the engine computes — so we can compare against the drawing's stated dims.
  C:\ClaudeVision\.venv\Scripts\python.exe C:\ClaudeVision\src\_dim_diagnose.py
"""
from pathlib import Path
import ezdxf
from ezdxf import bbox
import sys
sys.path.insert(0, r"C:\ClaudeVision\src")

JOB = Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay")

# Drawing-stated reference dims (from the PDFs JR would check against).
# Peg panel 1449: flat pattern ~525 x 553 ; Base plate 1450 ~497/535 ext ; header base 1455-C-001.
KNOWN = {
    "1449C": "PDF flat pattern states ~525.3 x 553.1 EXT (page 7)",
    "1450":  "PDF states 497.0 EXT fold, 535.2 / 558.3 EXT (page 9)",
    "1455-C-001": "PDF header base, 2x4.5 THRU, 493.6 O/D (page 12)",
    "1455-C-004": "PDF light bar 487 x 120 CRS, 2x4.2 THRU (page 15)",
}

try:
    from dxf_reader_py import extract_dxf_geometry, insunits_to_mm_factor
    HAVE_READER = True
except Exception as e:
    print("(could not import dxf_reader_py:", e, "- showing raw only)")
    HAVE_READER = False

dxfs = sorted(set(list(JOB.glob("*.dxf")) + list(JOB.glob("*.DXF"))))
for path in dxfs:
    name = path.name
    tag = next((k for k in KNOWN if k in name), None)
    try:
        doc = ezdxf.readfile(str(path))
    except Exception as ex:
        print(f"{name}: READ ERR {ex}"); continue
    insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    msp = doc.modelspace()
    ext = bbox.extents(msp)
    raw_w = round(ext.size.x, 3) if ext else None
    raw_h = round(ext.size.y, 3) if ext else None
    print(f"=== {name} ===")
    print(f"   INSUNITS={insunits}")
    if HAVE_READER:
        factor = insunits_to_mm_factor(insunits)
        print(f"   scale->mm factor: {factor}")
        print(f"   raw bbox: ({raw_w}, {raw_h})  ->  mm: ({round((raw_w or 0)*factor,2)}, {round((raw_h or 0)*factor,2)})")
        try:
            g = extract_dxf_geometry(path)
            print(f"   engine cut_length_mm: {g.get('estimated_cut_length_mm')}")
            print(f"   engine hole_count: {g.get('estimated_hole_count')}  bend_count: {g.get('estimated_bend_line_count')}")
            # show if engine reports its own bbox/dims
            for k in ("bbox_width_mm","bbox_height_mm","width_mm","height_mm","part_width_mm","part_height_mm"):
                if k in g:
                    print(f"   engine {k}: {g[k]}")
        except Exception as ex:
            print(f"   extract_dxf_geometry ERR: {ex}")
    else:
        print(f"   raw bbox: ({raw_w}, {raw_h})")
    if tag:
        print(f"   >>> COMPARE: {KNOWN[tag]}")
    print()
