#!/usr/bin/env python3
r"""
_probe_labour_costs_powder.py  —  READ-ONLY.

wb_populate writes one labour row per KEY in labour_estimate.costs_gbp (wb_populate
line 559-561). The workbook shows ~15 P.Coat lines but the part-level finish only
marks 4 parts as powder-coated. So costs_gbp must contain a P.Coat/powder key for
parts whose finish is NOT powder. This probe confirms that and shows the mismatch.

For every fabricated part it prints:
  - part_number, normalized_finish, textual_operations (the part's REAL ops)
  - the KEYS in labour_estimate.costs_gbp (what the labour writer will emit as rows)
  - a MISMATCH flag when costs_gbp has a powder/P.Coat key but the finish is NOT powder

That tells us: (a) is powder in costs_gbp for non-powder parts? (b) how many phantom
P.Coat lines? (c) which parts. Then we know WHERE to fix (the labour estimator that
builds costs_gbp), not wb_populate (which just writes what it's given).

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_labour_costs_powder.py ^
      "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
"""
import sys, json


def find_parts(obj):
    out, seen = [], set()
    def walk(o):
        if isinstance(o, dict):
            if "part_number" in o and ("labour_estimate" in o or "textual_operations" in o):
                if id(o) not in seen:
                    seen.add(id(o)); out.append(o)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(obj)
    best = {}
    for d in out:
        pn = str(d.get("part_number"))
        if pn not in best or len(d.keys()) > len(best[pn].keys()):
            best[pn] = d
    return list(best.values())


def finish_of(pe):
    return str(pe.get("normalized_finish") or (pe.get("surface_finishes") or [None])[0]
               or "?").upper()


def ops_of(pe):
    o = pe.get("textual_operations") or pe.get("operations") or []
    if isinstance(o, str): o = [o]
    return [str(x) for x in o]


def is_powder_key(k):
    k = str(k).lower()
    return "powder" in k or "p.coat" in k or "p/c" in k or "coat" in k


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    parts = find_parts(data)

    print("=" * 100)
    print("LABOUR costs_gbp vs FINISH — phantom P.Coat probe (read-only)")
    print("=" * 100)

    phantom = []
    total_powder_lines = 0
    for pe in sorted(parts, key=lambda p: str(p.get("part_number"))):
        pn = str(pe.get("part_number"))
        le = pe.get("labour_estimate") or {}
        costs = le.get("costs_gbp") or {}
        keys = list(costs.keys())
        fin = finish_of(pe)
        real_ops = ops_of(pe)
        powder_in_costs = [k for k in keys if is_powder_key(k)]
        powder_in_realops = any(is_powder_key(o) for o in real_ops)
        is_powder_finish = "POWDER" in fin

        if powder_in_costs:
            total_powder_lines += 1
            mismatch = ""
            if not is_powder_finish and not powder_in_realops:
                mismatch = "  <<< PHANTOM: costs_gbp has powder but finish/ops do NOT"
                phantom.append(pn)
            print(f"{pn:<14} finish={fin[:22]:<22} costs_keys={keys}")
            if mismatch:
                print(f"               real_ops={real_ops}{mismatch}")

    print("-" * 100)
    print(f"\nparts with a powder key in costs_gbp : {total_powder_lines}")
    print(f"of which PHANTOM (finish not powder)  : {len(phantom)} -> {phantom}")

    # show full costs_gbp for one phantom part so we can see the structure + where value comes from
    if phantom:
        pn0 = phantom[0]
        pe0 = next(p for p in parts if str(p.get("part_number")) == pn0)
        le0 = pe0.get("labour_estimate") or {}
        print(f"\nFULL labour_estimate for phantom part {pn0}:")
        print(f"  costs_gbp   = {le0.get('costs_gbp')}")
        print(f"  batch_hours = {le0.get('batch_hours')}")
        print(f"  finish      = {finish_of(pe0)}")
        print(f"  real ops    = {ops_of(pe0)}")
    print("=" * 100)
    print("Fix target: whatever builds labour_estimate.costs_gbp (labour estimator),")
    print("NOT wb_populate — it just writes one row per costs_gbp key.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_labour_costs_powder.py <summary.json>"); sys.exit(1)
    main(sys.argv[1])
