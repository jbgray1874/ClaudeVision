r"""READ-ONLY. Parity should compare SECTION SUBTOTALS (both sides have these), not fragile
line matches. Extract, for BOTH sides, the subtotals for:
  Unit cost | Standard Materials | Wire | Sheet Steel | Other Sheet Material | Labour
TIM: read the labelled subtotal cells from the Estimate sheet.
ENGINE: find the matching section subtotals in the summary JSON.
Show them side by side so we know the report can compare at this level. No edits."""
import re, json
import xlrd

# ---------- TIM side: section subtotals from the .xls ----------
MANUAL=r"K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls"
bk=xlrd.open_workbook(MANUAL); sh=bk.sheet_by_name("Estimate")
def cval(r,c):
    try: return sh.cell_value(r,c)
    except: return None
def rowtext(r):
    return " ".join(str(cval(r,c)) for c in range(sh.ncols) if cval(r,c) not in (None,""))

print("="*66); print("TIM — labelled subtotal rows (search)"); print("="*66)
wants = ["total material cost","total labour cost","total unit cost","unit cost",
         "sheet steel","other sheet","wire","standard material","sell price","rebate"]
tim_sect={}
for r in range(sh.nrows):
    txt=rowtext(r).lower()
    for w in wants:
        if w in txt:
            # last numeric on the row = the subtotal
            nums=[cval(r,c) for c in range(sh.ncols) if isinstance(cval(r,c),(int,float)) and cval(r,c)!=0]
            val = nums[-1] if nums else None
            print(f"  r{r:<3} '{w}': {val}   | {rowtext(r)[:70]}")
            break

# The headline cells we already know:
print("\n  Known cells: D6(qty)=",cval(5,3)," M115(unit)=",cval(114,12))

# ---------- ENGINE side: section subtotals from summary ----------
print("\n"+"="*66); print("ENGINE — section subtotals from summary JSON"); print("="*66)
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
es=S.get("estimate_summary",{})
wep=es.get("workbook_equivalent_pricing",{})
print("  workbook_equivalent_pricing:")
for k in ("m59_material_subtotal_gbp","m103_labour_subtotal_gbp","m105_total_unit_cost_gbp",
          "m107_rebate_fraction","m109_sell_margin_fraction","overhead_absorption_factor"):
    if k in wep: print(f"    {k} = {wep[k]}")

cb=S.get("cost_breakdown",{})
print("\n  cost_breakdown totals:")
print("    material.total =", cb.get("material",{}).get("total"))
print("    labour.total   =", cb.get("labour",{}).get("total"))

# per-part material, bucketed by how the engine would place them (standard/sheet/other/wire)
print("\n  Engine material by costing-basis bucket (to map to Tim's blocks):")
buckets={}
for p in (es.get("part_estimates") or []):
    ng=p.get("normalized_geometry",{}) or {}
    sf=ng.get("stock_form","?")
    mat=p.get("normalized_material","?")
    cost=p.get("extended_total_cost_gbp") or 0
    # crude bucket
    if mat and "STEEL" in str(mat).upper() and sf in ("sheet","stated_weight","plate"): b="sheet_steel-ish"
    elif "ACRYLIC" in str(mat).upper() or "PETG" in str(mat).upper(): b="other_sheet-ish"
    elif sf in ("tube","bar","wire"): b="section/tube"
    else: b="standard/other"
    buckets.setdefault(b,0.0); buckets[b]+=cost
for b,v in sorted(buckets.items()):
    print(f"    {b:<18} £{v:.2f}")

# powder + bought-in
pc=es.get("powder_coating_summary",{})
print("\n  powder total:", pc.get("powder_total_gbp"))
