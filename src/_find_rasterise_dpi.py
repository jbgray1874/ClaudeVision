r"""READ-ONLY. Which library rasterises the drawing image to ~300 DPI for the vision LLM? Find the
actual call + DPI, not from memory. Check the vision path modules for PyMuPDF (fitz) get_pixmap
with matrix/dpi, pdf2image, Pillow, or pdfplumber .to_image(resolution=). Show the exact lines +
the DPI/zoom used, in whichever module actually feeds the vision LLM. No edits."""
import os, re
SRC=r"C:\ClaudeVision\src"
def live(fn): return fn.endswith(".py") and not re.search(r"\.(bak|backup)|\.\d+\.py$|_old", fn)

# rasterisation patterns across all live modules
pats = {
  "fitz get_pixmap":   r"get_pixmap\s*\(",
  "fitz Matrix/zoom":  r"fitz\.Matrix\s*\(",
  "dpi= arg":          r"\bdpi\s*=",
  "resolution= arg":   r"\bresolution\s*=",
  "pdf2image":         r"convert_from_path|pdf2image",
  "Pillow Image":      r"from PIL|Image\.open|\.resize\(",
  "pdfplumber to_image":r"\.to_image\s*\(",
  "300":               r"\b300\b",
}
print("="*70); print("rasterisation calls across live src"); print("="*70)
hits=[]
for fn in sorted(os.listdir(SRC)):
    if not live(fn): continue
    p=os.path.join(SRC,fn)
    try: L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    except: continue
    for i,ln in enumerate(L):
        for name,pat in pats.items():
            if re.search(pat, ln):
                hits.append((fn,i+1,name,ln.strip()[:100]))
# group by file, only show files that have a real raster call (get_pixmap/convert/to_image/dpi/resolution)
from collections import defaultdict
byf=defaultdict(list)
for fn,i,name,ln in hits: byf[fn].append((i,name,ln))
raster_files=[fn for fn,items in byf.items() if any(n in ("fitz get_pixmap","pdf2image","pdfplumber to_image","dpi= arg","resolution= arg") for _,n,_ in items)]
for fn in raster_files:
    print(f"\n  {fn}:")
    for i,name,ln in byf[fn]:
        print(f"    {i}: [{name}] {ln}")

# zoom-to-DPI: for fitz, Matrix(z,z) means z*72 DPI. Show the zoom factor context.
print("\n"+"="*70); print("DPI/zoom detail in the vision path (fitz Matrix -> DPI = zoom*72)"); print("="*70)
for fn in ("vision_extractor.py","_bom_vision_reader.py","_vision_dim_proto.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): 
        print(f"  {fn}: (not present)"); continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(Matrix|get_pixmap|dpi|zoom|300|150|200|resolution)", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:100]}")
