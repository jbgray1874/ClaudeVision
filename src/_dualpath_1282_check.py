r"""READ-ONLY (calls reader, writes nothing). FAST. Enabling SDI_DUALPATH_BOM makes the dual-path
reader run on EVERY job including the 1282 anchor (£187.35). Before trusting it, check what the
dual-path reader produces for 1282 — does it give sensible rows (which would REPLACE 1282's baseline
BOM and could move the number), or error/empty (failure-isolated => 1282 stays on baseline, number
safe)? No full run. No edits."""
import sys, os, glob, json
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

hits=glob.glob(r"C:\ClaudeVision\output\json\1282*.json")
folder=None
if hits:
    S=json.load(open(hits[0],encoding="utf-8"))
    folder=S.get("job_folder") or os.path.dirname(S.get("full_path") or "")
print(f"1282 folder: {folder}")
if not folder or not os.path.isdir(folder):
    print("not reachable"); raise SystemExit

from bom_pipeline import reconciled_bom_rows_for_job
print("running dual-path reader on 1282...")
try:
    dp=reconciled_bom_rows_for_job(folder=folder)
    rows=dp.get("rows") or []
    print(f"\n1282 dual-path BOM: {len(rows)} rows")
    for r in rows[:20]:
        if isinstance(r,dict):
            code=r.get("part_code") or r.get("code") or r.get("part_number") or ""
            qty=r.get("qty") or r.get("quantity") or r.get("qty_per_unit") or ""
            desc=r.get("description") or r.get("desc") or ""
            print(f"  {str(code):<16} qty={str(qty):<4} {str(desc)[:44]}")
        else:
            print(f"  {str(r)[:88]}")
    print("\n  -> If these rows are SENSIBLE, enabling the flag will change 1282's BOM -> RE-RUN 1282")
    print("     once to confirm the new number, then that's the anchor. If empty/garbled, 1282 stays")
    print("     on baseline (failure-isolated) and £187.35 holds.")
except Exception as e:
    print(f"reader raised: {type(e).__name__}: {e}")
    print("  -> failure-isolated: 1282 would stay on baseline BOM, £187.35 safe.")
