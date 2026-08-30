r"""READ-ONLY. Pre-flight before the full 12120 re-run. Answer James's 3 questions:
  1) EXTRACTION ACCURACY: confirm parts/geometry/materials/BOM/routes read correctly (the key thing).
     Summarise: parts found, DXF match rate, gauges, finishes, BOM fasteners+qtys, routes fired.
  2) MANUAL ESTIMATE: does a 12120 manual .xls exist on the UNC share to price parity against?
     Run the deployed _find_manual_workbook (or glob the share) and report yes/no + path.
  3) CUSTOMER NAME: what does the quote generator currently derive (the '01-GA-' bug) and what's
     the REAL customer in the folder/drawing (Tesco?) so we can fix it.
No edits — a go/no-go + what-report-variant readout before the run."""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
jsons=[h for h in hits if 'report' not in h.lower() and 'quote' not in h.lower()]
JP=max(jsons, key=os.path.getmtime)
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}) or {}

print("="*66); print("1 — EXTRACTION ACCURACY SUMMARY"); print("="*66)
parts=es.get("part_estimates") or []
fab=[p for p in parts if str(p.get('part_number','')).startswith('12120-01-') and 'M' in str(p.get('part_number',''))[-3:]]
bi=[p for p in parts if str(p.get('part_number','')).upper().startswith('BI-') or str(p.get('part_number','')).upper().startswith('THUM')]
print(f"  parts total: {len(parts)} ({len(fab)} fabricated steel, {len(bi)} bought-in)")
# DXF match
dxf=S.get("dxf_augmentation",{}) or {}
print(f"  DXF: matched {dxf.get('matched_count') or dxf.get('matched')}, "
      f"unmatched {dxf.get('unmatched_dxf_count') or dxf.get('unmatched')}")
# gauges + finishes for fab parts
print("  fabricated parts (gauge / finish / material):")
for p in fab[:10]:
    th=p.get('normalized_thickness_mm') or (p.get('thicknesses_mm') or [None])[0]
    fin=(p.get('surface_finishes') or ['?'])[0] if p.get('surface_finishes') else '?'
    mat=p.get('normalized_material') or (p.get('materials') or ['?'])[0]
    print(f"    {p.get('part_number'):<16} t={th} finish={fin} mat={mat}")
# BOM fasteners + qty
print("  BOM fasteners (post-fix quantities):")
for p in bi:
    print(f"    {p.get('part_number'):<20} qty={p.get('quantity')} '{p.get('description','')[:26]}'")
# routes
ops=set()
for p in parts:
    proc=p.get('process_estimate',{}) or {}
    ops|=set((proc.get('unit_times_min') or {}).keys())
print(f"  routes fired: {sorted(ops)}")

print("\n"+"="*66); print("2 — MANUAL ESTIMATE for parity?"); print("="*66)
mp=None
try:
    import file_scan as FS
    if hasattr(FS,"_find_manual_workbook"):
        mp=FS._find_manual_workbook(S)
        print(f"  _find_manual_workbook -> {mp}")
except Exception as e:
    print(f"  helper raised: {e}")
if not mp:
    # glob the share for 12120 across years/customers
    for yr in ("2026","2025"):
        g=glob.glob(rf"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates\{yr}\**\*12120*\*.xls", recursive=True)
        g+=glob.glob(rf"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates\{yr}\**\12120*", recursive=True)
        if g:
            print(f"  glob {yr}: {g[:4]}")
            mp=g[0]; break
    if not mp:
        print("  no 12120 manual found on share -> run will produce NEW-JOB report (no parity)")
print(f"  => report variant: {'PARITY' if mp else 'NEW-JOB'}")

print("\n"+"="*66); print("3 — CUSTOMER NAME (the '01-GA-' bug)"); print("="*66)
print(f"  job_output_stem: {S.get('job_output_stem')}")
print(f"  job_folder: {S.get('job_folder')}")
# what fields might carry the real customer
for k in ("customer","client","customer_name","company"):
    if S.get(k): print(f"  S['{k}']: {S.get(k)}")
# scan first page title block text for a customer-ish token
pages=S.get("pages",[]) or []
if pages:
    rt=(pages[0].get("region_text") or {})
    tb=str(rt.get("title_block") or rt.get("notes") or "")[:300]
    print(f"  page1 title-block sample: {tb[:200]}")
print("  -> the quote took '01-GA-' from the folder name '12120-01-GA- ...'. Real customer likely")
print("     in title block or is Tesco (from job context). Fix: derive customer properly / allow override.")
