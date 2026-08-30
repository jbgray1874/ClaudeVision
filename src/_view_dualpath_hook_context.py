r"""READ-ONLY. Final context before writing the fix. I'll add a reconciliation step right after the
dual-path override (file_scan ~1219) that pushes dual-path fastener rows INTO part_estimates via
code-match (update qty) / token-match (_reconcile handles) / add-when-missing (clean code). Show:
  1) file_scan.py 1200-1228 exact (the dual-path block + surrounding, to insert after cleanly).
  2) How a bought-in part_estimate is SHAPED (fields: part_number, description, quantity,
     page_roles, material_estimate/extended_total_cost_gbp) so an ADDED pem stud row matches the
     shape the sheet expects.
  3) A clean-code helper approach: map 'STD PART'/'FIXING'/'FIXINGTBC' -> BI-<TYPE> from description.
No edits — gather the exact insertion context + part shape."""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"

print("="*66); print("1 — file_scan.py 1200-1228 (dual-path block + insert point)"); print("="*66)
p=os.path.join(SRC,"file_scan.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
for i in range(1199, min(len(L),1228)):
    print(f"  {i+1}: {L[i].rstrip()[:100]}")

print("\n"+"="*66); print("2 — shape of an existing bought-in part_estimate (all fields)"); print("="*66)
sys.path.insert(0, SRC)
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
S=json.load(open(hits[0],encoding="utf-8"))
parts=S.get("estimate_summary",{}).get("part_estimates") or []
for p in parts:
    if str(p.get("part_number","")).upper()=="BI-SELFCLINCHNUT":
        print(f"  BI-SELFCLINCHNUT full shape:")
        print(json.dumps(p, indent=2)[:1400])
        break
# also THUM620 (the one that came through) to see what a good bought-in fastener looks like
for p in parts:
    if str(p.get("part_number","")).upper()=="THUM620":
        print(f"\n  THUM620 full shape (the one that worked):")
        print(json.dumps(p, indent=2)[:1400])
        break
