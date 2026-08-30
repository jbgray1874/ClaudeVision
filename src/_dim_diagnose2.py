# -*- coding: utf-8 -*-
r"""Diagnose JR's 'dimensions slightly off' — v2, fixes the import (module is 'dxf_reader').
Shows the engine's DERIVED numbers (cut length, holes, bends, units_note) per part,
since the RAW bbox dims are already proven exact.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _dim_diagnose2.py
"""
from pathlib import Path
import sys, os
sys.path.insert(0, os.getcwd())
sys.path.insert(0, r"C:\ClaudeVision\src")

# The module is imported as 'dxf_reader' in file_scan.py; try that first, then fallbacks.
extract_dxf_geometry = None
for modname in ("dxf_reader", "dxf_reader_py"):
    try:
        mod = __import__(modname)
        extract_dxf_geometry = getattr(mod, "extract_dxf_geometry", None)
        if extract_dxf_geometry:
            print(f"(imported {modname}.extract_dxf_geometry)\n")
            break
    except Exception as e:
        print(f"(import {modname} failed: {e})")

JOB = Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay")
KNOWN = {
    "1449C": "drawing flat ~525.3 x 553.1 EXT; 386 holes (page 7)",
    "1450 - Base Plate_1.2mm MS_REV A": "drawing 535.2/558.3 EXT, 4 holes (page 9)",
    "1455-C-001": "header base, 4 holes, 6 bends (page 12)",
    "1455-C-004": "light bar 487x120, 2 holes, easy folds (page 15)",
}

if not extract_dxf_geometry:
    print("Could not import the reader. Run from C:\\ClaudeVision\\src"); raise SystemExit(1)

dxfs = sorted(set(list(JOB.glob("*.dxf")) + list(JOB.glob("*.DXF"))))
for path in dxfs:
    try:
        g = extract_dxf_geometry(path)
    except Exception as ex:
        print(f"=== {path.name} ===\n   EXTRACT ERR: {ex}\n"); continue
    print(f"=== {path.name} ===")
    print(f"   cut_length_mm : {g.get('estimated_cut_length_mm')}")
    print(f"   hole_count    : {g.get('estimated_hole_count')}   bend_count: {g.get('estimated_bend_line_count')}   pierce: {g.get('estimated_pierce_count')}")
    print(f"   hole_diameters: {g.get('hole_diameters_mm')}")
    print(f"   units_note    : {g.get('units_note')}")
    for k in ("bbox_width_mm","bbox_height_mm","width_mm","height_mm","area_mm2","dxf_weight_kg"):
        if k in g: print(f"   {k}: {g[k]}")
    tag = next((kk for kk in KNOWN if kk in path.name), None)
    if tag: print(f"   >>> COMPARE: {KNOWN[tag]}")
    print()
