r"""READ-ONLY. The bundle read £214.11/£108.63/£75.35 but the fresh spreadsheet says
£189.01/£133.45/£42.33. Suspect the summary JSON the bundle reads was NOT updated by the
12:22 populate run. Check: (1) the JSON's modified-time vs the fresh xlsx modified-time,
(2) the JSON's actual workbook_equivalent_pricing values, (3) whether a NEWER json exists
elsewhere (the run may write to a different path than the bundle reads). No edits."""
import os, json, glob, datetime

def mt(p):
    try: return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
    except: return "MISSING"

json_bundle_reads = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
fresh_xlsx = r"C:\ClaudeVision\output\estimates\1282 - Milwaukee Wall Bay_20260720_122217.xlsx"

print("="*66); print("TIMESTAMPS"); print("="*66)
print(f"  JSON bundle reads : {mt(json_bundle_reads)}  {json_bundle_reads}")
print(f"  fresh xlsx (12:22): {mt(fresh_xlsx)}  {os.path.basename(fresh_xlsx)}")

print("\n"+"="*66); print("JSON's actual values (is it stale?)"); print("="*66)
S=json.load(open(json_bundle_reads,encoding="utf-8"))
wep=S.get("estimate_summary",{}).get("workbook_equivalent_pricing",{})
for k in ("m59_material_subtotal_gbp","m103_labour_subtotal_gbp","m105_total_unit_cost_gbp","l105_total_unit_cost_gbp"):
    if k in wep: print(f"  {k} = {wep[k]}")
print(f"  document_total_estimated_cost_gbp = {S.get('document_total_estimated_cost_gbp') or S.get('estimate_summary',{}).get('document_total_estimated_cost_gbp')}")
print(f"  assumed_job_quantity = {S.get('estimate_summary',{}).get('estimate_workbook_inputs',{}).get('assumed_job_quantity')}")
print("\n  Fresh spreadsheet said: Material £133.45, Labour £42.33, Unit £189.01, qty 180")
print("  If JSON shows 108.63/75.35/214.11 -> JSON is STALE, not written by the 12:22 run.")

print("\n"+"="*66); print("Is there a NEWER 1282 json somewhere the run wrote?"); print("="*66)
for base in [r"C:\ClaudeVision\output\json", r"C:\ClaudeVision\output"]:
    for p in sorted(glob.glob(os.path.join(base,"**","*1282*.json"),recursive=True), key=os.path.getmtime, reverse=True)[:8]:
        print(f"  {mt(p)}  {p}")

# Does the run write the canonical json path? check saved_output_paths in the JSON itself
print("\n  saved_output_paths in the JSON:")
sop=S.get("saved_output_paths") or S.get("estimate_summary",{}).get("saved_output_paths") or {}
for k,v in (sop.items() if isinstance(sop,dict) else []):
    print(f"    {k}: {v}")
