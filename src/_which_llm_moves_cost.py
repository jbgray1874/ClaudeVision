r"""READ-ONLY. Is the £189.01->£187.95 drift from an LLM? Don't assume — locate every LLM call
that could affect a COST, and check whether it's already determinism-hardened (temp 0, seed).
Also record the CURRENT 1282 numbers so a re-run can be compared exactly.
No edits — measuring before concluding."""
import json, os, re

# 1) current numbers (to compare against a re-run)
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
es=S.get("estimate_summary",{})
wep=es.get("workbook_equivalent_pricing",{})
print("="*66); print("CURRENT 1282 numbers (compare a re-run to these)"); print("="*66)
print("  unit (WEP m105) =", wep.get("m105_total_unit_cost_gbp"))
print("  material (m59)  =", wep.get("m59_material_subtotal_gbp"))
print("  labour (m103)   =", wep.get("m103_labour_subtotal_gbp"))
print("  doc_total       =", es.get("document_total_estimated_cost_gbp"))
print("  source_of_truth =", wep.get("source_of_truth"))
# per-part costs snapshot (to see WHICH part moved on a re-run)
parts=es.get("part_estimates") or []
print(f"\n  per-part unit costs (n={len(parts)}):")
for p in parts:
    print(f"    {str(p.get('part_number')):<14} {p.get('normalized_material','?'):<10} qty={p.get('quantity')} unit=£{p.get('unit_total_cost_gbp')}")

# 2) which LLMs touch cost-bearing fields? scan src for LLM calls + their determinism settings
print("\n"+"="*66); print("LLM calls in the pipeline + determinism settings"); print("="*66)
SRC=r"C:\ClaudeVision\src"
llm_hits=[]
pat_llm=re.compile(r"(chat\.completions|messages\.create|grok|xai|openai|\.invoke\(|generate\(|temperature\s*=)", re.I)
for fn in os.listdir(SRC):
    if not fn.endswith(".py"): continue
    if re.search(r"\.(bak|backup|\d)", fn): continue
    p=os.path.join(SRC,fn)
    try: txt=open(p,encoding="utf-8",errors="replace").read()
    except: continue
    for i,ln in enumerate(txt.splitlines(),1):
        if pat_llm.search(ln):
            llm_hits.append((fn,i,ln.strip()[:90]))
# group by file
from collections import defaultdict
byf=defaultdict(list)
for fn,i,ln in llm_hits: byf[fn].append((i,ln))
for fn in sorted(byf):
    print(f"\n  {fn}:")
    for i,ln in byf[fn][:12]:
        print(f"    {i}: {ln}")

# 3) specifically: does vision/dimension extraction feed geometry (which feeds cost)?
print("\n"+"="*66); print("does any LLM feed GEOMETRY/DIMENSIONS (cost-bearing)?"); print("="*66)
for fn in ("vision_extractor.py","_vision_dim_proto.py","geometry_inference.py","json_normaliser.py"):
    p=os.path.join(SRC,fn)
    if os.path.exists(p):
        txt=open(p,encoding="utf-8",errors="replace").read()
        has_llm=bool(pat_llm.search(txt))
        has_temp=("temperature=0" in txt.replace(" ",""))
        has_seed=("seed=" in txt)
        print(f"  {fn:<24} has_llm={has_llm}  temp0={has_temp}  seed={has_seed}")
