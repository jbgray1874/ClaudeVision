# Why does 3886-02 have empty angles_deg when its PDF page shows DOWN 90 R 1?
# Check: which page is 3886-02 bound to, and does THAT page's text carry the callouts?
# vs 3886-03 which DID capture angles_deg:['90.00'].
import json, glob, os, re
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
J = json.load(open(f, encoding="utf-8"))

def walk(o, path="root"):
    if isinstance(o, dict):
        yield path, o
        for k,v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o): yield from walk(v, f"{path}[{i}]")

# 1) find each target's source page / page_number if recorded on the part
for tgt in ("3886-02","3886-03"):
    print("="*60); print(tgt); print("="*60)
    for path, node in walk(J):
        if isinstance(node, dict) and str(node.get("part_number") or "")==tgt:
            for k in ("source_page","page_number","source_pdf","bom_parent","filename_stem","dxf_file","page"):
                if node.get(k) is not None:
                    print(f"  {k}: {node.get(k)!r}")
            break
    print()

# 2) dump each PDF page's index + whether it contains DOWN/UP degree R + which part it seems to be
DOWN = re.compile(r"(DOWN|UP)\s*\d+\.?\d*°?\s*R", re.I)
PN = re.compile(r"\b3886-0[23]\b")
pages = None
for path, node in walk(J):
    if isinstance(node, dict) and isinstance(node.get("pages"), list) and path.count(".")<=1:
        pages = node["pages"]; break
if pages:
    print("PDF pages: fold-callout presence + 3886 part-number presence")
    for pg in pages:
        txt = str(pg.get("pdfplumber_text") or pg.get("normalized_text") or "")
        pnum = pg.get("page_number")
        has_down = bool(DOWN.search(txt))
        which = PN.findall(txt)
        ndown = len(DOWN.findall(txt))
        if has_down or which:
            print(f"  page {pnum}: DOWN/UP callouts={ndown}  3886-part-refs={set(which)}")
