r"""READ-ONLY. file_scan has NO real LLM (regex false-positive). Non-determinism in MATERIAL is
therefore either (a) a real LLM in ANOTHER module that feeds material, or (b) non-LLM: set/dict
ordering or last-writer-wins material assignment (the known three-source tension).
Find the TRUTH:
  1) Every REAL LLM call across src (messages.create / chat.completions / responses.create /
     client(...).invoke) — actual API calls, not the word 'grok' in a comment.
  2) For each, does that module touch material/thickness?
  3) Non-LLM drift sources: set() iteration feeding material, dict without sort, 'last-writer-wins'
     material assignment, normalise_material_for_part (the 931-935 code).
No edits — locate the actual source."""
import os, re
SRC=r"C:\ClaudeVision\src"
def live(fn): return not re.search(r"\.(bak|backup)|\.\d+\.py$|_old", fn)

# 1) REAL llm calls only (tight patterns)
print("="*66); print("REAL LLM API calls across src (tight match)"); print("="*66)
real_pat=re.compile(r"(\.messages\.create\(|\.chat\.completions\.create\(|\.responses\.create\(|client\.chat\(|\.invoke\()")
found={}
for fn in os.listdir(SRC):
    if not fn.endswith(".py") or not live(fn): continue
    p=os.path.join(SRC,fn)
    try: txt=open(p,encoding="utf-8",errors="replace").read()
    except: continue
    hits=[(i+1,l.strip()[:90]) for i,l in enumerate(txt.splitlines()) if real_pat.search(l)]
    if hits:
        found[fn]=(hits, ("material" in txt or "thickness" in txt))
for fn,(hits,mat) in sorted(found.items()):
    print(f"\n  {fn}  (touches material/thickness={mat}):")
    for i,l in hits: print(f"    {i}: {l}")
if not found:
    print("  NONE — no real LLM API calls in live src. Non-determinism is NON-LLM.")

# 2) non-LLM drift: material assignment order + set/dict iteration near material
print("\n"+"="*66); print("NON-LLM drift suspects: material assignment / set ordering"); print("="*66)
for fn in os.listdir(SRC):
    if not fn.endswith(".py") or not live(fn): continue
    p=os.path.join(SRC,fn); 
    try: L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    except: continue
    for i,ln in enumerate(L):
        s=ln.strip()
        # set() or dict iteration that could feed material non-deterministically
        if re.search(r"(normalize_material|normalise_material|last.?writer|material\s*=.*\bfor\b|for .* in set\(|\.pop\(\)|material.*=.*or\b.*or\b)", s, re.I):
            if "material" in s.lower() or "normalis" in s.lower() or "normaliz" in s.lower():
                print(f"  {fn}:{i+1}: {s[:96]}")

# 3) the known 931-935 material inheritance code
print("\n"+"="*66); print("file_scan.py material inheritance (the known-buggy region)"); print("="*66)
p=os.path.join(SRC,"file_scan.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
# find normalise_material_for_part def
for i,ln in enumerate(L):
    if re.search(r"def normalis|def normaliz", ln) and "material" in ln.lower():
        print(f"  found at line {i+1}: {ln.strip()[:80]}")
        for j in range(i, min(len(L), i+30)):
            print(f"    {j+1}: {L[j].rstrip()[:96]}")
        break

# 4) does material_estimate pick a price from a set/dict that could reorder?
print("\n"+"="*66); print("material PRICE source ordering (BoughtInCatalogue dup-price issue?)"); print("="*66)
for fn in ("pricing_service.py","bought_in_pricing.py","file_scan.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(price.*=.*\[0\]|first|\.pop\(|order by|ORDER BY|random|shuffle|dict\(|set\()", ln) and re.search(r"price|cost|catalog", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:96]}")
