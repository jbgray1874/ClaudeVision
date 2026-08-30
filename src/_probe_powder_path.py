#!/usr/bin/env python3
r"""
_probe_powder_path.py  —  READ-ONLY. Writes nothing.

1282 workbook shows ~15 P.Coat lines at a flat £10.81 each (~£150 powder), vs Tim's
~£13.60 (6 batched, size-scaled, assembly-level lines). We need to fix powder for the
1282 parity report. Before patching, this probe answers, from the real JSON:

  A. WHICH parts get a P.Coat / powder_coating operation, and what is each part's
     FINISH? (RAW parts should NOT be powder-coated — flag them.)
  B. For each powder part: the throughput value the labour line uses (the flat
     369.0037 / 184.5018 constant?), and whether the part ALSO carries a computed
     powder area (m2_per_part / powder_m2) that the labour line is IGNORING.
  C. Where powder_coating is INFERRED from (finish text? operation map?) so we know
     where to add a RAW guard.

Prints per powder-carrying part: PN, finish, has_m2?, m2 value, throughput used,
and a verdict (RAW->should suppress / flat-rate->should size-scale / ok).

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_powder_path.py ^
      "C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
"""
import sys, json


def find_parts(obj):
    out, seen = [], set()
    def walk(o):
        if isinstance(o, dict):
            if "part_number" in o and ("textual_operations" in o or "operations" in o
                                       or "normalized_finish" in o or "labour_estimate" in o):
                if id(o) not in seen:
                    seen.add(id(o)); out.append(o)
            for v in o.values(): walk(v)
        elif isinstance(o, list):
            for v in o: walk(v)
    walk(obj)
    # keep most-hydrated per PN
    best = {}
    for d in out:
        pn = str(d.get("part_number"))
        score = len(d.keys())
        if pn not in best or score > len(best[pn].keys()):
            best[pn] = d
    return list(best.values())


def ops_of(pe):
    o = pe.get("textual_operations") or pe.get("operations") or []
    if isinstance(o, str): o = [o]
    return [str(x).lower() for x in o]


def deep_find(o, needle, path="pe"):
    hits = []
    if isinstance(o, dict):
        for k, v in o.items():
            if needle in k.lower():
                disp = v if not isinstance(v, (dict, list)) else f"<{type(v).__name__}>"
                hits.append((f"{path}.{k}", disp))
            hits += deep_find(v, needle, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            hits += deep_find(v, needle, f"{path}[{i}]")
    return hits


def finish_of(pe):
    return str(pe.get("normalized_finish") or (pe.get("surface_finishes") or [None])[0]
               or pe.get("finish") or "?").upper()


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    parts = find_parts(data)

    print("=" * 96)
    print("POWDER / P.COAT PATH PROBE (read-only)")
    print("=" * 96)

    powder_parts = [pe for pe in parts if any("powder" in o or "coat" in o for o in ops_of(pe))]
    print(f"{len(powder_parts)} of {len(parts)} parts carry a powder/coat operation.\n")

    print(f"{'part':<14}{'finish':<26}{'m2?':<6}{'m2_val':<10}{'throughput':<12}{'verdict'}")
    print("-" * 96)

    for pe in sorted(powder_parts, key=lambda p: str(p.get("part_number"))):
        pn = str(pe.get("part_number"))[:13]
        fin = finish_of(pe)[:25]
        # look for any powder area figure anywhere in the part
        m2_hits = deep_find(pe, "m2") + deep_find(pe, "powder_area") + deep_find(pe, "area_m")
        m2_hits = [(p, v) for p, v in m2_hits if isinstance(v, (int, float))]
        has_m2 = "Y" if m2_hits else "-"
        m2_val = f"{m2_hits[0][1]:.4f}" if m2_hits else "-"
        # look for the throughput / batch_hours on the powder labour line
        le = pe.get("labour_estimate") or {}
        thr_hits = deep_find(pe, "throughput") + deep_find(pe, "batch_hours") + deep_find(pe, "run_min")
        thr = ""
        for p, v in thr_hits:
            if isinstance(v, (int, float)):
                thr = f"{v:.2f}"; break
        thr = thr or "-"

        verdict = "ok"
        if "RAW" in fin:
            verdict = ">> RAW: should NOT powder"
        elif has_m2 == "Y":
            verdict = "flat-rate; m2 exists -> size-scale"
        else:
            verdict = "flat-rate; no m2 found"
        print(f"{pn:<14}{fin:<26}{has_m2:<6}{m2_val:<10}{thr:<12}{verdict}")

    print("-" * 96)

    # show where powder_coating is inferred + all m2 / powder paths on one sample part
    print("\nWHERE POWDER IS INFERRED (finish + operation-map paths on a powder part):")
    sample = powder_parts[0] if powder_parts else None
    if sample:
        print(f"  sample part: {sample.get('part_number')}")
        for p, v in deep_find(sample, "finish"):
            print(f"    {p} = {v}")
        for p, v in deep_find(sample, "m2"):
            print(f"    {p} = {v}")
        for p, v in deep_find(sample, "powder"):
            print(f"    {p} = {v}")
        for p, v in deep_find(sample, "throughput"):
            print(f"    {p} = {v}")

    raw_powder = [pe for pe in powder_parts if "RAW" in finish_of(pe)]
    print(f"\nSUMMARY:")
    print(f"  powder-carrying parts : {len(powder_parts)}")
    print(f"  of which RAW finish   : {len(raw_powder)}  -> {[str(p.get('part_number')) for p in raw_powder]}")
    print("=" * 96)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_powder_path.py <summary.json>"); sys.exit(1)
    main(sys.argv[1])
