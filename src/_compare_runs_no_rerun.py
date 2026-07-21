r"""READ-ONLY. Diagnose £189.01 -> £187.95 WITHOUT re-running. Everything we need is on disk:
  1) The CURRENT JSON (the £187.95 run) — its numbers + per-part costs + source_of_truth.
  2) The populated .xlsx files in output\estimates\ — list them with timestamps; the NEWEST is the
     £187.95 run, an OLDER one is £189.01. Their filenames/mtimes bracket what changed when.
  3) Whether the current JSON's WEP was stamped by readback (source_of_truth) — tells us if £187.95
     is the REAL Excel number or a stale reconstruction.
  4) main.py backups (bak_wepreadback / bak_svgsize timestamps) vs the estimate mtimes — did a code
     change land BETWEEN the two estimate runs? That would point to code, not the LLM.
No edits — reading the record instead of re-running."""
import json, os, glob, datetime

def ts(p): 
    try: return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M:%S")
    except: return "?"

# 1) current JSON numbers
JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}); wep=es.get("workbook_equivalent_pricing",{})
print("="*66); print("CURRENT JSON (the £187.95 run)"); print("="*66)
print("  json mtime      =", ts(JP))
print("  unit (m105)     =", wep.get("m105_total_unit_cost_gbp"))
print("  material (m59)  =", wep.get("m59_material_subtotal_gbp"))
print("  labour (m103)   =", wep.get("m103_labour_subtotal_gbp"))
print("  source_of_truth =", wep.get("source_of_truth"), " <- if 'populated_xlsx_excel_com', £187.95 IS the real Excel number")
print("  unit_cost_source=", (wep.get('assumptions') or {}).get('unit_cost_source'))

# 2) all populated estimates for 1282, with timestamps (newest vs older bracket the change)
print("\n"+"="*66); print("populated .xlsx history (output\\estimates) — brackets the change"); print("="*66)
est_dir=r"C:\ClaudeVision\output\estimates"
xs=sorted(glob.glob(os.path.join(est_dir,"*1282*.xls*")), key=os.path.getmtime)
for p in xs[-8:]:
    print(f"  {ts(p)}  {os.path.basename(p)}")

# 3) code-change backups vs estimate mtimes — did code land BETWEEN runs?
print("\n"+"="*66); print("main.py backups (code changes) — did any land between the two runs?"); print("="*66)
src=r"C:\ClaudeVision\src"
for p in sorted(glob.glob(os.path.join(src,"main.py.bak_*")), key=os.path.getmtime):
    print(f"  {ts(p)}  {os.path.basename(p)}")
print("  main.py (live) mtime =", ts(os.path.join(src,"main.py")))

# 4) per-part costs in current JSON (so if we DO have an older JSON backup, we can diff parts)
print("\n"+"="*66); print("per-part costs in CURRENT JSON (baseline for any diff)"); print("="*66)
parts=es.get("part_estimates") or []
tot=0.0
for p in parts:
    u=p.get("unit_total_cost_gbp") or 0; q=p.get("quantity") or 0
    tot+=(u*q if isinstance(u,(int,float)) and isinstance(q,(int,float)) else 0)
    print(f"    {str(p.get('part_number')):<14} {str(p.get('normalized_material')):<10} qty={q} unit=£{u} ext=£{p.get('extended_total_cost_gbp')}")
print(f"  sum of extended part costs = £{round(tot,2)}")

# 5) is there an older JSON backup anywhere to diff against?
print("\n"+"="*66); print("any older 1282 JSON backups to diff? (json dir + archive)"); print("="*66)
for d in (r"C:\ClaudeVision\output\json", r"C:\ClaudeVision\output\archive\json"):
    if os.path.isdir(d):
        for p in sorted(glob.glob(os.path.join(d,"*1282*")), key=os.path.getmtime):
            print(f"  {ts(p)}  {p}")
