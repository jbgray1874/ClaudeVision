r"""READ-ONLY. The dual-path BOM is HYBRID on the sheet: THUM620 qty 4 (dual-path won) but
BI-SELFCLINCHNUT qty 1 + BI-KNURLEDKNOB qty 1 (baseline placeholders survived). The dual-path
direct test showed self-clinch nut qty 4, knurled knob qty 2 — so those rows EXIST in dual-path but
didn't reach the sheet. Diagnose the merge:
  1) When SDI_DUALPATH_BOM applies _da['bom_rows']=_dp['rows'] (file_scan 1219), does something
     DOWNSTREAM re-merge baseline BI- placeholders back in, or pick per-row?
  2) In the 12120 JSON: which BOM parts have dual-path provenance vs baseline (BI-/placeholder)?
     Show part_number + source + qty for each BOM line to see the split.
  3) Where do the BI-SELFCLINCHNUT / BI-KNURLEDKNOB placeholders get injected AFTER the dual-path
     override (so they survive)? Search the bought-in / synthesize path.
No edits — find why dual-path rows are partially overwritten by placeholders."""
import os, re, json, glob

hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
JP=hits[0] if hits else None
print(f"12120 JSON: {JP}\n")
if JP:
    S=json.load(open(JP,encoding="utf-8"))
    # 1) what's in document_analysis.bom_rows (the dual-path target) vs the final part_estimates BOM?
    da=S.get("document_analysis",{}) or {}
    dp_rows=da.get("bom_rows") or []
    print("="*66); print(f"document_analysis.bom_rows (dual-path target): {len(dp_rows)} rows"); print("="*66)
    for r in dp_rows[:20]:
        if isinstance(r,dict):
            code=r.get("part_code") or r.get("code") or r.get("part_number") or ""
            qty=r.get("qty") or r.get("quantity") or r.get("qty_per_unit") or ""
            print(f"    {str(code):<20} qty={qty}")

    print("\n"+"="*66); print("final BOM part_estimates (what reached the sheet): source + qty"); print("="*66)
    parts=S.get("estimate_summary",{}).get("part_estimates") or []
    for p in parts:
        pn=str(p.get("part_number") or "")
        if pn.startswith("BI-") or pn.startswith("THUM") or pn in ("PACKAGING","DELIVERY","POWDER","STD PART","FIXING","FIXINGTBC") or "SELFCLINCH" in pn.upper() or "KNURLED" in pn.upper():
            me=p.get("material_estimate",{}) or {}
            ps=me.get("price_source"); src=ps.get("supplier_source") if isinstance(ps,dict) else ps
            print(f"    {pn:<22} qty={p.get('quantity')} method={me.get('cost_method')} src={src}")

print("\n"+"="*66); print("2 — where BI- placeholders get injected (does it run AFTER dual-path?)"); print("="*66)
SRC=r"C:\ClaudeVision\src"
for fn in ("file_scan.py","document_builder.py","bay_rollup.py","json_normaliser.py","estimator.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(BI-|SELFCLINCH|KNURLED|synthesize_folder_job_bom|inject_missing_bay|prose_recogniser|bought_in_recognised|_reconcile_bought)", ln):
            if "def " in ln or "=" in ln or "append" in ln.lower() or "synthesize" in ln.lower() or "inject" in ln.lower():
                print(f"  {fn}:{i+1}: {ln.strip()[:96]}")

print("\n"+"="*66); print("3 — the merge/override order: dual-path (1219) vs synthesize (1643)"); print("="*66)
p=os.path.join(SRC,"file_scan.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
for i in range(1635,1655):
    if i < len(L): print(f"  {i+1}: {L[i].rstrip()[:96]}")
print("  -> if synthesize/inject at ~1643 runs AFTER dual-path override at 1219 and re-adds")
print("     BI- placeholders, that's why they survive. The dual-path rows should be authoritative.")
