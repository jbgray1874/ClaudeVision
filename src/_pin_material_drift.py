r"""READ-ONLY. Real LLMs (_bom_vision_reader, tech_radar) aren't in the 1282 populate path and
tech_radar's material-touch is analysis, not estimating. So MATERIAL drift is NON-LLM: iteration
order in material normalisation or price selection. Show the two exact functions:
  1) json_normaliser.normalise_material_for_part (165-) + normalise_material (153-) — does it read
     candidate materials from a dict/set (unordered) and pick one? Order-dependent = drift.
  2) bought_in_pricing compose (336-) 'priority order' + prices_by_qty dict() — is the price picked
     from an unordered collection? The dup-SKU-two-prices issue = non-deterministic winner.
  3) Any dict()/set()/.keys()/.values() iteration in these that isn't sorted.
No edits — read the exact code that picks material + its price."""
import os, re
SRC=r"C:\ClaudeVision\src"

def dump(fn, start_pat, n=40, label=""):
    p=os.path.join(SRC,fn); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(start_pat, ln):
            print(f"\n  --- {fn}:{i+1} {label} ---")
            for j in range(i, min(len(L), i+n)):
                print(f"    {j+1}: {L[j].rstrip()[:100]}")
            return
    print(f"  {fn}: pattern {start_pat!r} not found")

print("="*66); print("1 — normalise_material_for_part (does it pick from unordered candidates?)"); print("="*66)
dump("json_normaliser.py", r"def normalise_material_for_part", 45, "(material picker)")

print("\n"+"="*66); print("2 — bought_in_pricing compose (price priority order)"); print("="*66)
dump("bought_in_pricing.py", r"Compose catalogue_pricers in priority order", 40, "(price picker)")

print("\n"+"="*66); print("3 — unsorted dict/set/keys iteration in material+price code"); print("="*66)
for fn in ("json_normaliser.py","bought_in_pricing.py","pricing_service.py"):
    p=os.path.join(SRC,fn); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        # iteration over dict/set that could vary, near material/price/candidate
        if re.search(r"(for .* in .*(\.keys\(\)|\.values\(\)|\.items\(\))|for .* in set\(|for .* in \{|next\(iter\(|\.pop\(\)|list\(set\()", ln):
            ctx=" ".join(L[max(0,i-1):i+2]).lower()
            if any(t in ctx for t in ("material","price","cost","candidate","supplier","catalog","match")):
                if "sorted(" not in ln:  # flag only UNSORTED
                    print(f"  {fn}:{i+1}: {ln.strip()[:96]}")

# 4) also: how is the material CANDIDATE chosen when multiple sources disagree (last-writer-wins)?
print("\n"+"="*66); print("4 — multi-source material resolution (last-writer-wins?)"); print("="*66)
for fn in ("json_normaliser.py","file_scan.py","drawing_job_merge.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(normalized_material|normalised_material)\s*=", ln) and "def " not in ln:
            print(f"  {fn}:{i+1}: {ln.strip()[:96]}")
