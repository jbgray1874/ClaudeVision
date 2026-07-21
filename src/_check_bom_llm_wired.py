r"""READ-ONLY. Q: is the BOM-reading LLM path still WIRED and FIRING, or backed out/skipped for
12120? Check the DEPLOYED code + the 12120 output. Establish:
  1) Is the BOM LLM extractor (_bom_vision_reader / bom_table_extractor / vision BOM path) still
     imported and CALLED by the live scan flow (file_scan / main), or is the import commented /
     removed / behind a disabled flag?
  2) Is there a flag (env/config) that gates the BOM LLM, and is it ON? (SKIP_*, USE_*, VISION_*)
  3) Did it FIRE for 12120 — any bom-llm / vision-bom markers in the 12120 JSON (used_llava,
     vision_model, bom extraction provenance)?
  4) What actually PRODUCED 12120's BOM lines — trace the source (note-scan / manual json / table).
No edits — is the LLM path live+firing, or backed out?"""
import os, re, json, glob

SRC=r"C:\ClaudeVision\src"
def live(fn): return fn.endswith(".py") and not re.search(r"\.(bak|backup)|\.\d+\.py$|_old", fn)

print("="*68); print("1 — is a BOM LLM extractor imported/called by the live scan flow?"); print("="*68)
for fn in ("file_scan.py","main.py","document_builder.py","json_normaliser.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(_bom_vision|bom_table_extractor|bom_reader|extract_bom|read_bom|bom_llm|vision.*bom|bom.*vision|merge_boms)", ln, re.I):
            commented = ln.strip().startswith("#")
            print(f"  {fn}:{i+1}: {'[COMMENTED] ' if commented else ''}{ln.strip()[:92]}")

print("\n"+"="*68); print("2 — how BOM rows actually get built in the live path (the real source)"); print("="*68)
# where does the BOM/bought-in list come from in file_scan/document_builder?
for fn in ("file_scan.py","document_builder.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(job_bought_in_materials|bought_in.*json|note.?scan|prose_recogn|bought_in_recognised|BI-|catalogue.*bought|bom_rows\s*=)", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:92]}")

print("\n"+"="*68); print("3 — flags gating any vision/LLM BOM path (and their default)"); print("="*68)
for fn in ("file_scan.py","vision_extraction.py","config.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"getenv\(.*(BOM|VISION|SKIP|USE_LLM|LLM)", ln) or re.search(r"(SKIP_VISION|USE_BOM|BOM_LLM|VISION_USE)", ln):
            print(f"  {fn}:{i+1}: {ln.strip()[:92]}")

print("\n"+"="*68); print("4 — did any LLM/vision BOM path FIRE for 12120?"); print("="*68)
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
if hits:
    S=json.load(open(hits[0],encoding="utf-8")); blob=json.dumps(S)
    for marker in ["used_llava","vision_model","reconciled","bom_vision","llava","bom_table",
                   "prose_recogniser","bought_in_recognised","note_scan","job_bought_in"]:
        c=blob.count(marker)
        print(f"    '{marker}': {c} occurrence(s)")
    # provenance of the BI- parts
    parts=S.get("estimate_summary",{}).get("part_estimates") or []
    print("\n    BI-/placeholder part provenance:")
    for pp in parts:
        pn=str(pp.get("part_number") or "")
        if pn.startswith("BI-") or pn in ("PACKAGING","DELIVERY","POWDER"):
            me=pp.get("material_estimate",{}) or {}
            ps=me.get("price_source"); src=ps.get("supplier_source") if isinstance(ps,dict) else ps
            print(f"      {pn:<20} method={me.get('cost_method')} src={src}")
else:
    print("  no 12120 JSON found")
