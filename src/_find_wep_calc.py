r"""READ-ONLY. ROOT CAUSE: same fresh JSON has document_total=188.38 (matches spreadsheet ~189)
but workbook_equivalent_pricing m59/m103/m105 = 108.63/75.35/214.11 (does NOT). Two parallel
pricing calcs disagree. Find where workbook_equivalent_pricing is computed, and whether it uses
different inputs (e.g. pre-DXF material, old labour) than the spreadsheet/document_total. So we
know why m59/m103/m105 are stale relative to the real estimate. No edits."""
import os, re, glob

# which file computes workbook_equivalent_pricing / m59_material_subtotal_gbp?
print("="*66); print("who computes workbook_equivalent_pricing (m59/m103/m105)?"); print("="*66)
for p in glob.glob(r"C:\ClaudeVision\src\*.py"):
    if os.path.getsize(p)>2_000_000: continue
    try: txt=open(p,encoding="utf-8",errors="replace").read()
    except: continue
    if "workbook_equivalent_pricing" in txt or "m59_material_subtotal" in txt or "m103_labour_subtotal" in txt:
        print(f"\n  {os.path.basename(p)}:")
        for i,ln in enumerate(txt.splitlines()):
            if re.search(r"workbook_equivalent_pricing|m59_material_subtotal|m103_labour_subtotal|m105_total_unit|l105_total_unit|def .*equivalent|equivalent_pricing", ln):
                print(f"    {i+1}: {ln.strip()[:100]}")

# and where does document_total_estimated_cost_gbp come from (the CORRECT one)?
print("\n"+"="*66); print("who computes document_total_estimated_cost_gbp (the correct 188.38)?"); print("="*66)
for p in glob.glob(r"C:\ClaudeVision\src\*.py"):
    if os.path.getsize(p)>2_000_000: continue
    try: txt=open(p,encoding="utf-8",errors="replace").read()
    except: continue
    if "document_total_estimated_cost_gbp" in txt:
        for i,ln in enumerate(txt.splitlines()):
            if re.search(r"document_total_estimated_cost_gbp\s*[=:]", ln):
                print(f"  {os.path.basename(p)}:{i+1}: {ln.strip()[:96]}")
