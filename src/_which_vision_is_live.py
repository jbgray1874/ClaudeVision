r"""READ-ONLY. Item 2: make the LIVE vision path render at 300 DPI. First find WHICH vision module
the populate pipeline actually calls (don't patch a dead one). Trace:
  1) What main.py / file_scan / the scan flow imports + calls for vision dimension extraction.
  2) Each vision module's render DPI: vision_extraction.py (Matrix 2,2=144?), _bom_vision_reader.py
     (300), concept_brief_extractor.py (Matrix 2,2), and any others.
  3) Which one is on the DIMENSION/GEOMETRY path (feeds cost) vs BOM-table or concept-brief paths.
No edits — identify the live vision renderer + its DPI before patching."""
import os, re
SRC=r"C:\ClaudeVision\src"
def live(fn): return fn.endswith(".py") and not re.search(r"\.(bak|backup)|\.\d+\.py$|_old", fn)

print("="*66); print("1 — vision imports/calls in the main scan flow"); print("="*66)
for fn in ("main.py","file_scan.py","geometry_inference.py","json_normaliser.py","dxf_reader.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(vision_extract|_bom_vision|concept_brief|_vision_dim|import.*vision|from.*vision|render_page_to_png|vision_dims|extract_dims)", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:96]}")

print("\n"+"="*66); print("2 — render DPI in each vision module"); print("="*66)
for fn in os.listdir(SRC):
    if not live(fn): continue
    if not re.search(r"vision|concept_brief", fn, re.I): continue
    p=os.path.join(SRC,fn); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(fitz\.Matrix|get_pixmap|dpi\s*=|zoom\s*=|/\s*72)", ln):
            # compute DPI if Matrix(z,z)
            mz=re.search(r"Matrix\(\s*([\d.]+)\s*,\s*([\d.]+)", ln)
            note=""
            if mz: note=f"  => {float(mz.group(1))*72:.0f} DPI"
            print(f"  {fn}:{i+1}: {ln.strip()[:80]}{note}")

print("\n"+"="*66); print("3 — which module is the DIMENSION path (feeds cost)?"); print("="*66)
# what calls set part dimensions/geometry from vision?
for fn in os.listdir(SRC):
    if not live(fn): continue
    p=os.path.join(SRC,fn); 
    try: L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    except: continue
    for i,ln in enumerate(L):
        if re.search(r"(vision.*dim|dim.*vision|vision.*geometry|bounding_box.*vision|from _?vision)", ln, re.I) and "def " not in ln:
            print(f"  {fn}:{i+1}: {ln.strip()[:90]}")

print("\n  NOTE: _bom_vision_reader = BOM TABLE reader (no-DXF packs). vision_extraction = ?")
print("        Need to see which (if any) is called during a normal DXF-backed scan like 1282.")
