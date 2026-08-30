r"""READ-ONLY. RISK MAP: workbook_equivalent_pricing (the stale £214.11 block) is read by
multiple consumers. Determine the blast radius: which LIVE code paths consume m59/m103/m105/
l105, and whether the PRIMARY spreadsheet (wb_populate, which correctly produced £189.01) reads
the stale block anywhere. Distinguish live files from dead copies (.backup, 1, _old, 3, 4).
No edits — establishing exposure before deciding the fix scope."""
import os, re, glob

LIVE = {"estimate_full_parity_report.py","xlsx_output.py","pricing_service.py","pricing_variance.py",
        "estimate_parity_pretty_report.py","wb_populate.py","main.py","estimator.py","document_builder.py"}
DEADish = re.compile(r"(\.backup|\.bak|_old|_rewrite|\d)\.py$|backup\.py$")

print("="*70); print("1 — does wb_populate (PRIMARY, made £189.01) read the stale WEP block?"); print("="*70)
wbp=r"C:\ClaudeVision\src\wb_populate.py"
if os.path.exists(wbp):
    txt=open(wbp,encoding="utf-8",errors="replace").read()
    hits=[(i+1,ln.strip()) for i,ln in enumerate(txt.splitlines())
          if re.search(r"workbook_equivalent_pricing|m59_material|m103_labour|m105_total|l105_total", ln)]
    if hits:
        print("  wb_populate READS workbook_equivalent_pricing at:")
        for n,l in hits: print(f"    {n}: {l[:96]}")
    else:
        print("  wb_populate does NOT read workbook_equivalent_pricing — it computes independently.")
        print("  -> the £189.01 spreadsheet is NOT tainted by the stale block. GOOD.")
    # what DOES wb_populate use for its totals?
    print("\n  wb_populate's own total sources:")
    for i,ln in enumerate(txt.splitlines()):
        if re.search(r"material_total|labour_total|unit_cost|document_total|total_material|total_labour|_subtotal", ln, re.I):
            print(f"    {i+1}: {ln.strip()[:92]}")

print("\n"+"="*70); print("2 — LIVE consumers of the stale block (exclude dead copies)"); print("="*70)
for p in sorted(glob.glob(r"C:\ClaudeVision\src\*.py")):
    b=os.path.basename(p)
    if DEADish.search(b): continue          # skip dead copies
    if os.path.getsize(p)>2_000_000: continue
    try: txt=open(p,encoding="utf-8",errors="replace").read()
    except: continue
    reads=[(i+1,ln.strip()) for i,ln in enumerate(txt.splitlines())
           if re.search(r"\.get\(.*m105_total_unit|\.get\(.*m59_material|\.get\(.*m103_labour|\.get\(.*l105_total|workbook_equiv.*\.get", ln)]
    if reads:
        tag="LIVE" if b in LIVE else "?"
        print(f"\n  [{tag}] {b}: reads stale-block fields")
        for n,l in reads[:6]: print(f"    {n}: {l[:90]}")

print("\n"+"="*70); print("3 — which of these actually run in a normal populate (main.py imports)?"); print("="*70)
mp=open(r"C:\ClaudeVision\src\main.py",encoding="utf-8",errors="replace").read()
for mod in ["xlsx_output","pricing_service","pricing_variance","estimate_full_parity_report","estimate_parity_pretty_report"]:
    m=re.search(rf"(from {mod} import|import {mod})", mp)
    # is it in the normal-run path or behind a flag?
    print(f"  {mod}: {'imported in main.py' if m else 'NOT imported'}")
