r"""READ-ONLY of code (calls the reader, writes nothing to the pipeline). FAST. Before flipping the
flag + full re-run, test the dual-path BOM reader DIRECTLY against 12120's folder to confirm it
produces REAL rows (FIXING codes + quantities), not generic placeholders. This proves bom_pipeline
is complete and worth enabling — in seconds, no full populate.
"""
import sys, os, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

# find 12120's folder from its JSON
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
folder=None
if hits:
    import json
    S=json.load(open(hits[0],encoding="utf-8"))
    folder=S.get("job_folder") or os.path.dirname(S.get("full_path") or "")
print(f"12120 folder: {folder}")
if not folder or not os.path.isdir(folder):
    print("folder not found/reachable; trying Live Enquiry glob...")
    g=glob.glob(r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\12120*")
    folder=g[0] if g else None
    print(f"  -> {folder}")
if not folder:
    raise SystemExit

try:
    from bom_pipeline import reconciled_bom_rows_for_job
except Exception as e:
    print(f"CANNOT import bom_pipeline: {type(e).__name__}: {e}")
    print("  -> the dual-path reader may be incomplete. That's why the flag is off.")
    raise SystemExit

print("\ncalling reconciled_bom_rows_for_job (pdfplumber + Grok reconciled)...")
try:
    dp = reconciled_bom_rows_for_job(folder=folder)
except Exception as e:
    print(f"reader raised: {type(e).__name__}: {e}")
    raise SystemExit

rows = dp.get("rows") or []
print(f"\nDUAL-PATH BOM: {len(rows)} rows")
print("="*70)
for r in rows[:25]:
    if isinstance(r, dict):
        code = r.get("part_code") or r.get("code") or r.get("part_number") or ""
        desc = r.get("description") or r.get("desc") or ""
        qty = r.get("qty") or r.get("quantity") or r.get("qty_per_unit") or ""
        price = r.get("price") or r.get("unit_price") or ""
        print(f"  {str(code):<16} qty={str(qty):<4} {str(desc)[:40]:<40} £{price}")
    else:
        print(f"  {str(r)[:90]}")
print("="*70)
findings=dp.get("findings") or []
print(f"findings: {len(findings)}")
for f in findings[:5]:
    print(f"  {str(f)[:100]}")
print("\n-> Does this show Tim's REAL codes (FIXING2906/2057/2908/62, qtys 4/4/2/2/2/4)?")
print("   If YES -> flip SDI_DUALPATH_BOM=1 and re-run. If placeholders -> reader needs work.")
