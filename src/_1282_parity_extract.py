r"""READ-ONLY. Pull the exact parity numbers from the bundle + both workbooks so the 1282
parity diagnostic HTML (7692 house style) is built on real data. Dumps: money-cell comparisons
(the 4 fails), material/labour totals engine vs manual, and the per-line BOM reconciliation."""
import json, os

b = r"C:\ClaudeVision\output\csv\1282_parity_bundle.json"
if not os.path.exists(b):
    b = r"C:\ClaudeVision\output\csv\estimate_full_parity_bundle.json"
J = json.load(open(b, encoding="utf-8"))
print("bundle keys:", list(J.keys()), "\n")

# money cells (the match/fail rows)
print("="*70); print("MONEY CELL COMPARISONS"); print("="*70)
for r in (J.get("money_cell_comparisons") or []):
    lbl = r.get("label") or r.get("cell") or r.get("json_path") or "?"
    jn = r.get("json_numeric"); wb = r.get("workbook_cached_numeric")
    st = r.get("status") or r.get("verdict") or ""
    print(f"  {str(lbl)[:44]:<46} engine={jn}  manual={wb}  [{st}]")

# totals / reverse-engineered workbook
print("\n"+"="*70); print("TOTALS"); print("="*70)
rev = J.get("reverse_engineered_workbook") or {}
for k in ("material","labour","total","unit_cost"):
    v = rev.get(k)
    if isinstance(v, dict):
        print(f"  {k}: engine={v.get('ai') or v.get('json')}  manual={v.get('workbook') or v.get('manual')}")
    elif v is not None:
        print(f"  {k}: {v}")
# also try status_counts + headline
print("  status_counts:", J.get("status_counts"))
for k in ("job","drawing_no","quantity","engine_unit_cost","manual_unit_cost"):
    if J.get(k) is not None: print(f"  {k}: {J.get(k)}")

# BOM reconciliation
print("\n"+"="*70); print("BOM RECONCILIATION (matched / manual-only / ai-only counts)"); print("="*70)
recon = J.get("bom_set_reconciliation") or {}
for k in ("match_rate_pct","manual_line_count","matched_count","manual_only_count","ai_only_count","genuine_miss_count","out_of_scope_count"):
    if k in recon: print(f"  {k}: {recon[k]}")
print("\n  -- manual_only (lines Tim has, engine missing) --")
for r in (recon.get("manual_only") or [])[:20]:
    print(f"     {str(r.get('code') or r.get('part_number'))[:16]:<18} {str(r.get('description'))[:40]:<42} £{r.get('manual_cost_gbp')}  [{r.get('category')}]")
print("\n  -- ai_only (engine has, Tim doesn't) --")
for r in (recon.get("ai_only") or [])[:20]:
    print(f"     {str(r.get('code') or r.get('part_number'))[:16]:<18} {str(r.get('description'))[:40]:<42} £{r.get('ai_cost_gbp')}")

# labour route comparisons
print("\n"+"="*70); print("LABOUR ROUTE (op code: engine hours vs workbook hours)"); print("="*70)
for r in (J.get("labour_route_comparisons") or [])[:30]:
    op = r.get("operation") or r.get("op_code") or "?"
    ah = r.get("ai_hours_decimal") or r.get("json_hours"); wh = r.get("workbook_hours_decimal")
    ac = r.get("ai_line_cost_gbp"); wc = r.get("workbook_line_cost_gbp")
    print(f"  {str(op)[:20]:<22} engine_h={ah} manual_h={wh}  engine£={ac} manual£={wc}")
