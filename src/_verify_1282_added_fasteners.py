r"""READ-ONLY. The reconcile ADDS 3 fasteners to 1282 (FIXING5 dome rivet, FIXING236 nutsert,
FIXING125 glide). Confirm these are GENUINE 1282 BOM parts (real codes from the drawing table), not
dual-path misreads — so the ADDs are correct, not noise. Check:
  1) Do these codes/descriptions appear in 1282's dual-path rows with coherent data?
  2) Does 1282's manual estimate (Tim's .xls) list a dome rivet / nutsert / glide? (If Tim has them,
     the ADDs are definitely right — we were missing what Tim books.)
  3) Are they already somewhere in the JSON under a different identity (dup risk)?
"""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

hits=glob.glob(r"C:\ClaudeVision\output\json\1282*.json")
S=json.load(open(hits[0],encoding="utf-8"))

print("="*66); print("1 — the 3 fasteners in 1282's dual-path rows"); print("="*66)
from bom_pipeline import reconciled_bom_rows_for_job
folder=S.get("job_folder") or os.path.dirname(S.get("full_path") or "")
dp=reconciled_bom_rows_for_job(folder=folder)
for r in dp.get("rows") or []:
    code=str(r.get("part_code") or r.get("code") or r.get("part_number") or "")
    if code.upper() in ("FIXING5","FIXING236","FIXING125"):
        print(f"  {code:<12} qty={r.get('qty') or r.get('quantity')} desc='{r.get('description','')}'")

print("\n"+"="*66); print("2 — does Tim's 1282 manual list rivet/nutsert/glide?"); print("="*66)
# find + read the manual via the deployed helper if possible
try:
    import file_scan as FS
    mp = FS._find_manual_workbook(S) if hasattr(FS,"_find_manual_workbook") else None
except Exception as e:
    mp=None; print(f"  (helper lookup skipped: {e})")
if not mp:
    g=glob.glob(r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\Manual Estimates\2026\TTI\1282*\*.xls")
    mp=g[0] if g else None
print(f"  manual: {mp}")
if mp and os.path.exists(mp):
    try:
        import xlrd
        wb=xlrd.open_workbook(mp); sh=wb.sheet_by_index(0)
        found=[]
        for rx in range(sh.nrows):
            row=" ".join(str(sh.cell_value(rx,cx)) for cx in range(sh.ncols)).upper()
            for kw in ("RIVET","NUTSERT","GLIDE"):
                if kw in row:
                    found.append((kw, row.strip()[:90]))
        if found:
            print("  Tim's manual mentions:")
            for kw,txt in found[:12]:
                print(f"    [{kw}] {txt}")
        else:
            print("  no rivet/nutsert/glide keyword found in Tim's manual sheet")
    except Exception as e:
        print(f"  (couldn't read manual: {e})")

print("\n"+"="*66); print("3 — dup risk: are these already in JSON under another identity?"); print("="*66)
blob=json.dumps(S).upper()
for kw in ("RIVET","NUTSERT","GLIDE"):
    print(f"  '{kw}' appears {blob.count(kw)}x in 1282 JSON")
parts=S.get("estimate_summary",{}).get("part_estimates") or []
print("  current 1282 bought-in parts:")
for p in parts:
    pn=str(p.get("part_number","")).upper()
    if pn.startswith("BI-") or pn.startswith("FIXING") or "RIVET" in str(p.get("description","")).upper():
        print(f"    {p.get('part_number')} qty={p.get('quantity')} '{p.get('description','')[:30]}'")
