r"""READ-ONLY. The report's §5 checklist lists EVERY part with a generic 'engine-flagged; confirm
content' and no reason — useless noise. Diagnose against real 1282 JSON:
  1) What does estimate_review_signals.parts_flagged ACTUALLY contain? All 30 parts, or a real
     subset? And do the entries have a 'reason'/'signal' field, or is it empty (forcing the generic
     fallback)?
  2) Show the raw structure of a few parts_flagged entries + the thresholds/recommendation.
So I can fix §5 to show only GENUINELY flagged parts WITH their real reason, not all parts. No edits."""
import json
JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
ers=S.get("estimate_summary",{}).get("estimate_review_signals",{}) or {}

print("="*66); print("estimate_review_signals structure"); print("="*66)
print(f"  keys: {list(ers)}")
print(f"  flagged_part_count: {ers.get('flagged_part_count')}")
print(f"  thresholds: {json.dumps(ers.get('thresholds'))[:200]}")
print(f"  recommendation: {str(ers.get('recommendation'))[:150]}")

pf=ers.get("parts_flagged") or []
print(f"\n  parts_flagged: {len(pf)} entries")
print("  -- first 5 raw entries --")
for e in pf[:5]:
    print(f"    {json.dumps(e)[:200]}")

# what fields do the entries have?
if pf:
    allkeys=set()
    for e in pf:
        if isinstance(e,dict): allkeys.update(e.keys())
    print(f"\n  entry keys present: {sorted(allkeys)}")
    # is there a reason-like field anywhere?
    for cand in ("reason","signal","note","signals","reasons","why","flags","flag_reasons"):
        vals=[e.get(cand) for e in pf if isinstance(e,dict) and e.get(cand)]
        if vals:
            print(f"    '{cand}' populated in {len(vals)} entries, e.g.: {str(vals[0])[:120]}")

# compare to total parts
total=len(S.get("estimate_summary",{}).get("part_estimates") or [])
print(f"\n  total part_estimates: {total}")
print(f"  -> flagged {len(pf)}/{total} — {'ALL parts (signal meaningless)' if len(pf)>=total else 'a subset (real signal)'}")
