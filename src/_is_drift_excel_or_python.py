r"""READ-ONLY. Material picker + price picker are both deterministic (sequential if/return; ordered
list). So the drift may NOT be in Python at all — it could be EXCEL. The readback opens the .xlsx
and runs CalculateFull; if the template has a VOLATILE function (NOW/TODAY/RAND/OFFSET/INDIRECT) or
iterative calc on a circular ref, the SAME inputs give DIFFERENT computed numbers each recalc.
That would look exactly like 'material moves, labour stable' if a volatile cell feeds material.

This probe:
  1) Snapshots current per-part MATERIAL COST from the JSON to a file (baseline for a 1-run diff).
  2) Reports the JSON's material subtotal so we know the Python-side material number.
  3) Flags: is the JSON material number STABLE (it's the Python calc) or does it match the drifting
     Excel number? If source_of_truth=excel_com, the m59 in JSON came FROM Excel — so if THAT moves
     run-to-run but the per-part Python costs DON'T, the drift is in EXCEL, not Python.
No edits — separate the Excel hypothesis from the Python hypothesis."""
import json, os

JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}); wep=es.get("workbook_equivalent_pricing",{})
parts=es.get("part_estimates") or []

# 1) sum the PYTHON-side per-part material costs (independent of Excel)
py_mat=0.0
rows=[]
for p in parts:
    me=p.get("material_estimate",{}) or {}
    ext=me.get("extended_material_cost_gbp")
    unit=me.get("unit_material_cost_gbp")
    q=p.get("quantity") or 0
    v=ext if isinstance(ext,(int,float)) else ((unit*q) if isinstance(unit,(int,float)) and q else 0)
    py_mat+=v
    rows.append((str(p.get("part_number")), str(p.get("normalized_material")), unit, ext, q))

print("="*66); print("PYTHON-side material total vs EXCEL-side (WEP m59)"); print("="*66)
print(f"  sum of per-part extended material (PYTHON) = £{round(py_mat,4)}")
print(f"  WEP m59 material subtotal (from EXCEL)     = £{wep.get('m59_material_subtotal_gbp')}")
print(f"  source_of_truth                            = {wep.get('source_of_truth')}")
print(f"  cost_breakdown material total              = £{(es.get('cost_breakdown',{}).get('material') or {}).get('total')}")
print("\n  -> KEY TEST: after the next run, compare BOTH numbers to these.")
print("     If PYTHON per-part total is STABLE but EXCEL m59 MOVED -> drift is in EXCEL (volatile cell).")
print("     If PYTHON per-part total MOVED -> drift is in the Python material calc.")

# 2) write baseline snapshot for a 1-run diff
snap={"py_material_total": round(py_mat,4),
      "excel_m59": wep.get("m59_material_subtotal_gbp"),
      "unit_m105": wep.get("m105_total_unit_cost_gbp"),
      "labour_m103": wep.get("m103_labour_subtotal_gbp"),
      "parts": [{"pn":pn,"mat":mat,"unit_mat":u,"ext_mat":e,"qty":q} for pn,mat,u,e,q in rows]}
snap_path=r"C:\ClaudeVision\output\_material_baseline_snapshot.json"
json.dump(snap, open(snap_path,"w",encoding="utf-8"), indent=2, default=str)
print(f"\n  baseline snapshot written: {snap_path}")

# 3) check the template for volatile functions (needs the populated xlsx; note if openpyxl available)
print("\n"+"="*66); print("VOLATILE functions in the template? (NOW/TODAY/RAND/OFFSET/INDIRECT)"); print("="*66)
import glob
est_dir=r"C:\ClaudeVision\output\estimates"
xs=sorted(glob.glob(os.path.join(est_dir,"*1282*.xls*")), key=os.path.getmtime)
if xs:
    newest=xs[-1]
    print(f"  newest populated xlsx: {os.path.basename(newest)}")
    try:
        import openpyxl
        wb=openpyxl.load_workbook(newest, data_only=False)  # formulas, not values
        vol=("NOW(","TODAY(","RAND(","RANDBETWEEN(","OFFSET(","INDIRECT(","INFO(","CELL(")
        hits=[]
        for ws in wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value,str) and c.value.startswith("="):
                        up=c.value.upper()
                        for v in vol:
                            if v in up:
                                hits.append((ws.title,c.coordinate,v,c.value[:50]))
        if hits:
            print(f"  FOUND {len(hits)} volatile-function cell(s):")
            for t,coord,v,f in hits[:20]:
                print(f"    {t}!{coord}: {v} in {f}")
        else:
            print("  none found — Excel calc should be deterministic (drift is Python or read-timing).")
        # iterative calc enabled? (circular refs)
        try:
            cp=wb.calculation
            print(f"  iterative calc: {getattr(cp,'iterate',None)}  maxIterations={getattr(cp,'iterateCount',None)}")
        except Exception: pass
    except ImportError:
        print("  (openpyxl not available here — run flags this; check on machine)")
    except Exception as e:
        print(f"  (couldn't scan: {e})")
else:
    print("  no populated 1282 xlsx found")
