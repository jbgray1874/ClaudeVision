r"""READ-ONLY. Confirm the token patch worked in the rebuilt bundle: matched_count should now
reflect the code_stem matches (expected ~4: ELECTRICS/FIXING125/FIXING5/VINYL76), the '1.0'
garbage codes should be GONE from manual_only, and show the match_kind on each matched line.
Verify by effect, don't assume. No edits."""
import json
b=r"C:\ClaudeVision\output\csv\1282_parity_bundle.json"
J=json.load(open(b,encoding="utf-8"))
recon=J.get("bom_set_reconciliation",{})

print("="*60); print("RECON COUNTS (after token patch)"); print("="*60)
for k in ("matched_count","manual_only_count","ai_only_count","genuine_miss_count","out_of_scope_count","match_rate_pct"):
    print(f"  {k}: {recon.get(k)}")

print("\n--- matched lines (with match_kind) ---")
for m in (recon.get("matched") or []):
    print(f"  {str(m.get('code'))[:24]:<26} kind={m.get('match_kind','code')!r:<12} "
          f"ai_code={m.get('ai_code','—')} manual£={m.get('manual_cost_gbp')} ai£={m.get('ai_cost_gbp')} var={m.get('variance_pct')}")

print("\n--- manual_only: is the '1.0' garbage GONE? ---")
junk=[r for r in (recon.get("manual_only") or []) if str(r.get('code')).strip() in ('1.0','1','0.0','0')]
print(f"  numeric-junk codes remaining: {len(junk)}")
print("  manual_only codes:", [r.get('code') for r in (recon.get("manual_only") or [])])

print("\n--- ai_only codes ---")
print("  ", [r.get('code') for r in (recon.get("ai_only") or [])])
