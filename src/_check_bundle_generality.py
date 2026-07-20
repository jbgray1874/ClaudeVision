r"""READ-ONLY. The report must be GENERAL (any job), so it reads only the bundle. Check what
the bundle's label-scan totals-discovery ALREADY captures generically (by label, not fixed
cell). Two parts:
  1) Dump the bundle's totals_discovery hits + money_cell_comparisons — these are found by
     LABEL SCAN, so they work for any job/template. See if section subtotals are among them.
  2) Show the bundle-builder's totals label-scan code (what labels it searches for) so we know
     if 'Sheet Steel'/'Other Sheet'/'Standard Materials' subtotals are captured or need adding.
No edits — establishing what's already general vs what must be added, once, generically."""
import json, os, re

# 1) what the bundle already captured by label-scan
b=r"C:\ClaudeVision\output\csv\1282_parity_bundle.json"
J=json.load(open(b,encoding="utf-8"))
print("="*66); print("1 — bundle label-scan hits (GENERIC, any job)"); print("="*66)
disc=J.get("estimate_sheet_discovery",{})
td=disc.get("totals_discovery",{})
print("  totals_discovery.mode:", td.get("mode"))
for h in (td.get("hits") or []):
    print(f"    label={h.get('label')!r:<34} cell={h.get('label_cell')}->{h.get('value_cell')} src={h.get('value_source')}")

print("\n  money_cell_comparisons (label + both values):")
for r in (J.get("money_cell_comparisons") or []):
    print(f"    {str(r.get('label'))[:32]:<34} cell={r.get('cell'):<5} eng={r.get('json_numeric')} tim={r.get('workbook_cached_numeric')} [{r.get('status')}]")

# 2) the bundle-builder's label list (what it scans for) — is it extensible to sections?
print("\n"+"="*66); print("2 — bundle-builder totals label-scan (what labels it seeks)"); print("="*66)
p=r"C:\ClaudeVision\src\estimate_full_parity_report.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()
# find money_cells / label targets
for i,ln in enumerate(L):
    if re.search(r"money_cell|total material|total labour|total unit|sheet steel|other sheet|standard material|label_targets|TARGET_LABELS|_LABELS|scan.*label|full_sheet_label_scan", ln, re.I):
        print(f"  {i+1}: {ln.strip()[:112]}")

# 3) is there a config list of the cells/labels compared? (ESTIMATE_FULL_PARITY.money_cells)
print("\n"+"="*66); print("3 — config-driven money_cells list (generic target definition)"); print("="*66)
cfg=r"C:\ClaudeVision\src\config.py"
if os.path.exists(cfg):
    cl=open(cfg,encoding="utf-8",errors="replace").read().splitlines()
    grab=False
    for i,ln in enumerate(cl):
        if re.search(r"ESTIMATE_FULL_PARITY|money_cells|parity.*label", ln, re.I):
            grab=True
        if grab:
            print(f"  {i+1}: {ln.rstrip()[:112]}")
            if grab and ln.strip().endswith("}") and "money_cells" not in ln: 
                if i>0 and "ESTIMATE_FULL_PARITY" not in ln: break
