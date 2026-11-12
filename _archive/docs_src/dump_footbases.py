"""
Diagnostic: dump the 3886-02 / 3886-03 footbase blanks + powder detail so we can
see why 3886-02 powder labour is £17.82 while its mirror floors at £1.53.

Usage (from C:\\ClaudeVision\\src):
    python dump_footbases.py
    python dump_footbases.py "C:\\ClaudeVision\\output\\json\\1282 - Milwaukee Wall Bay.json"
"""
import json
import sys

DEFAULT_JSON = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"


def find(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from find(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from find(v, key)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_JSON
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    ps = (d.get("estimate_summary", {}) or {}).get("part_estimates", []) or []

    for tag in ("3886-02", "3886-03"):
        p = next((x for x in ps if str(x.get("part_number", "")).startswith(tag)), None)
        print("=" * 60)
        print(tag)
        if p is None:
            print("  (not found)")
            continue
        me = p.get("material_estimate", {}) or {}
        print(f"  blank L,W mm : {me.get('blank_length_mm')}  x  {me.get('blank_width_mm')}")
        print(f"  blank area m2: {me.get('blank_area_m2')}")
        print(f"  cost_method  : {me.get('cost_method')}")
        print("  powder_consumable:")
        print(json.dumps(me.get("powder_consumable"), indent=2))
        seen = set()
        for det in find(p, "powder_coating_detail"):
            key = json.dumps(det, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            print("  powder_labour_detail:")
            print(json.dumps(det, indent=2))
        # also surface the powder labour £ if present
        for costs in find(p, "labour_cost_breakdown_gbp"):
            if isinstance(costs, dict) and "powder_coating" in costs:
                print(f"  powder_coating labour £: {costs.get('powder_coating')}")
                break


if __name__ == "__main__":
    main()
