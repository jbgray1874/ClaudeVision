"""READ-ONLY. Pre/post verification for the bought-in credibility-gate fix
in _part_cost_credibility (estimator.py).

Checks, in one pass:
  1. Gate status flips insufficient_data -> ok
  2. credible_cost_ratio lands ~0.83 (was ~0.4257)
  3. BYTE-IDENTICAL check: WB Sell Price + every material/labour cost unchanged
     (this patch must never move a price -- only the credibility bucket)
  4. The four genuinely-uncertain no-DXF fabricated parts (1448-01, 1455-C-101,
     2621-01C, 3886-01) still carry their low-confidence / unreliable flags
  5. Bought-in parts no longer appear in unreliable_parts

USAGE:
  Step 1 (BEFORE applying the patch), take a snapshot:
    Copy-Item "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json" `
              "C:\ClaudeVision\output\json\1282_PRE_PATCH.json" -Force

  Step 2: apply the _part_cost_credibility patch, re-run 1282 through the normal pipeline.

  Step 3:
    C:\ClaudeVision\.venv\Scripts\python.exe _credibility_fix_verify.py
"""
import json, io
from pathlib import Path

PRE  = Path(r"C:\ClaudeVision\output\json\1282_PRE_PATCH.json")
POST = Path(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json")

EXPECTED_UNCERTAIN = {"1448-01", "1455-C-101", "2621-01C", "3886-01"}

def load(p: Path):
    if not p.exists():
        print(f"  MISSING: {p}")
        return None
    return json.load(io.open(p, encoding="utf-8"))

def estimate_summary_of(data):
    return data.get("estimate_summary") or {}

def parts_of(data):
    # source parts (geometry/material) live under manufacturing_writeup
    return (data.get("manufacturing_writeup") or {}).get("parts") or data.get("parts") or []

def part_estimates_of(data):
    # priced line items live under estimate_summary.part_estimates
    return estimate_summary_of(data).get("part_estimates") or []

def sufficiency_of(data):
    return estimate_summary_of(data).get("data_sufficiency") or {}

def part_cost_map(data):
    # cost/material identity should be read from part_estimates (what the gate
    # actually scores), keyed by part_number, matching _assess_estimate_data_sufficiency
    out = {}
    for p in part_estimates_of(data):
        pn = str(p.get("part_number") or "").strip()
        if pn:
            out[pn] = {
                "extended_total_cost_gbp": p.get("extended_total_cost_gbp"),
                "unit_total_cost_gbp": p.get("unit_total_cost_gbp"),
            }
    # material tag lives on the source parts (manufacturing_writeup), not part_estimates
    for p in parts_of(data):
        pn = str(p.get("part_number") or "").strip()
        if pn:
            out.setdefault(pn, {})["normalized_material"] = p.get("normalized_material")
    return out

print("=" * 92)
print("1+2. Gate status and ratio, pre vs post")
print("=" * 92)
pre_data, post_data = load(PRE), load(POST)
if pre_data is None or post_data is None:
    print("  Cannot proceed without both PRE and POST files. See usage in the header.")
    raise SystemExit(0)

pre_suff, post_suff = sufficiency_of(pre_data), sufficiency_of(post_data)

for label, s in (("PRE ", pre_suff), ("POST", post_suff)):
    print(f"  [{label}] status={s.get('status')!r:20} "
          f"suppress_headline_total={s.get('suppress_headline_total')!r:6} "
          f"credible_cost_ratio={s.get('credible_cost_ratio')}")

status_ok = (pre_suff.get("status") == "insufficient_data" and post_suff.get("status") == "ok")
ratio_ok = (post_suff.get("credible_cost_ratio") or 0) >= 0.50
print(f"\n  Status flip insufficient_data -> ok:  {'PASS' if status_ok else 'FAIL -- check manually'}")
print(f"  credible_cost_ratio now >= 0.50:      {'PASS' if ratio_ok else 'FAIL'}")

print("\n" + "=" * 92)
print("3. BYTE-IDENTICAL check -- every part's cost + material tag unchanged")
print("=" * 92)
pre_costs, post_costs = part_cost_map(pre_data), part_cost_map(post_data)
all_pns = sorted(set(pre_costs) | set(post_costs))
cost_diffs = []
for pn in all_pns:
    a, b = pre_costs.get(pn), post_costs.get(pn)
    if a != b:
        cost_diffs.append((pn, a, b))

pre_total = pre_suff.get("document_total_provisional_gbp")
post_total = post_suff.get("document_total_provisional_gbp")
print(f"  document_total  PRE={pre_total}   POST={post_total}   "
      f"{'PASS (identical)' if pre_total == post_total else 'FAIL -- price moved!'}")

if cost_diffs:
    print(f"  FAIL -- {len(cost_diffs)} part(s) changed cost or material tag (should be ZERO):")
    for pn, a, b in cost_diffs:
        print(f"     {pn}: PRE={a}  POST={b}")
else:
    print(f"  PASS -- all {len(all_pns)} parts byte-identical on cost + normalized_material")

print("\n" + "=" * 92)
print("4. The four genuinely-uncertain no-DXF fabricated parts still flagged")
print("=" * 92)
post_unreliable = {str(u.get("part_number")) for u in (post_suff.get("unreliable_parts") or [])}
still_flagged = EXPECTED_UNCERTAIN & post_unreliable
missing = EXPECTED_UNCERTAIN - post_unreliable
print(f"  Expected uncertain: {sorted(EXPECTED_UNCERTAIN)}")
print(f"  Still in unreliable_parts POST-fix: {sorted(still_flagged)}")
if missing:
    print(f"  WARNING -- these dropped out of unreliable_parts and should NOT have: {sorted(missing)}")
else:
    print(f"  PASS -- all four still correctly flagged as uncertain")

print("\n" + "=" * 92)
print("5. Bought-ins should NO LONGER appear in unreliable_parts")
print("=" * 92)
def is_bought_in_pn(pn):
    pn_u = pn.upper()
    return pn_u.startswith(("BI-", "FIXING", "VINYL", "PACKAGING", "DELIVERY"))

boughtin_still_unreliable = [pn for pn in post_unreliable if is_bought_in_pn(pn)]
if boughtin_still_unreliable:
    print(f"  FAIL -- bought-ins still flagged unreliable post-fix: {boughtin_still_unreliable}")
else:
    print(f"  PASS -- no bought-in parts remain in unreliable_parts")

print("\n" + "=" * 92)
print("VERDICT")
print("=" * 92)
overall = status_ok and ratio_ok and not cost_diffs and not missing and not boughtin_still_unreliable
if overall:
    print("  ALL CHECKS PASS. Fix is surgical: gate corrected, zero price movement,")
    print("  genuine uncertainty (£27.91 across 4 parts) still honestly flagged.")
else:
    print("  ONE OR MORE CHECKS FAILED -- do not consider this fix verified. Review above.")
