"""READ-ONLY. Find where junction box / mains cable / earth strap / downlights got their
prices (£1.04 / £0.42 / £1.04 / £26). Reads the actual output JSON and dumps each item's
source, cost_source, price_verified flag and review_flags - so we can see if it's the LLM
backstop, a fallback pricer, or a stub default, and whether it's honestly flagged.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _trace_phantom_prices.py
"""
import json, io

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(io.open(P, encoding="utf-8"))

TARGETS = ["JUNCTION", "MAINS", "EARTH", "DOWNLIGHT", "LOOM", "LED LINK"]

def match(desc):
    u = (desc or "").upper()
    return any(t in u for t in TARGETS)

parts = data.get("parts", [])
found = [p for p in parts if match(p.get("description","")) or match(p.get("part_number",""))]

print(f"{len(found)} electrical item(s) in output JSON:\n")
for p in found:
    print("=" * 72)
    print(f"  {p.get('part_number')}  |  {p.get('description')}")
    print("=" * 72)
    for k in ("source", "cost_source", "price_verified",
              "unit_cost_gbp", "unit_material_cost_gbp", "extended_total_cost_gbp",
              "_layer2_recognised", "_matched_historical_desc", "_matched_code",
              "_match_score", "_queue_for_catalogue", "_no_price_reason"):
        if k in p:
            print(f"     {k:28} = {p.get(k)!r}")
    rf = p.get("review_flags") or []
    if rf:
        print(f"     review_flags:")
        for f in rf:
            print(f"        - {f}")
    # any other price-ish keys we didn't anticipate?
    other = [k for k in p.keys() if ("cost" in k.lower() or "price" in k.lower() or "source" in k.lower())
             and k not in ("source","cost_source","price_verified","unit_cost_gbp",
                           "unit_material_cost_gbp","extended_total_cost_gbp")]
    if other:
        print(f"     other price/source keys: {[(k, p.get(k)) for k in other]}")
    print()
