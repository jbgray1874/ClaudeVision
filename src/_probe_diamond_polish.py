#!/usr/bin/env python3
r"""
_probe_diamond_polish.py  —  READ-ONLY.

diamond_polish appears as a labour op on 12532-02-02M and 12532-03-05M, but BOTH are
POWDER COATED (Polyester Matt / Matt). A powder-coated part is not diamond-polished —
these are mutually exclusive finishes. So diamond_polish here is SPURIOUS (likely the
'CHROME PLATING - POLISHING' boilerplate in the general notes misfiring into an op).

Currently it costs £0 (not in OP_NAME_MAP -> WB rate lookup returns 0), so it doesn't
inflate the total, but it's a visibly-wrong labour line. We want to SUPPRESS it, like
the powder gate suppresses powder on non-powder parts.

This probe confirms, for every part carrying diamond_polish:
  - its normalized_finish (is it powder? then diamond_polish is definitely spurious)
  - its full textual_operations
  - whether ANY part has a GENUINE polish finish (POLISHED, MIRROR, DIAMOND) where
    diamond_polish would be REAL and must NOT be suppressed

Builds the gate rule: suppress diamond_polish when finish is powder/RAW (not a polish
finish). Fail-safe: if a part genuinely has a polished/mirror finish, KEEP it.

Usage:
  C:\ClaudeVision\.venv\Scripts\python.exe _probe_diamond_polish.py ^
      "C:\ClaudeVision\output\json\12532-03RecipeCard.json"
"""
import sys, json


def find_mw_parts(data):
    return (data.get("manufacturing_writeup") or {}).get("parts") or []


def find_estimate_parts(data):
    return (data.get("estimate_summary") or {}).get("part_estimates") or []


def ops_of(pe):
    o = pe.get("textual_operations") or pe.get("operations") or []
    if isinstance(o, str): o = [o]
    return [str(x) for x in o]


def has_diamond(pe):
    return any("diamond" in str(o).lower() or "polish" in str(o).lower() for o in ops_of(pe)) \
        or ("diamond_polish" in ((pe.get("labour_estimate") or {}).get("costs_gbp") or {}))


def main(jpath):
    data = json.load(open(jpath, "r", encoding="utf-8"))
    mw = find_mw_parts(data)
    est = find_estimate_parts(data)

    # index fuller records by PN for finish lookup
    finish_by_pn = {}
    ops_by_pn = {}
    for p in mw:
        pn = str(p.get("part_number") or "")
        finish_by_pn[pn] = str(p.get("normalized_finish") or "")
        ops_by_pn[pn] = ops_of(p)

    print("=" * 92)
    print("DIAMOND_POLISH SUPPRESSION PROBE (read-only)")
    print("=" * 92)

    # parts with diamond_polish anywhere
    carriers = []
    for p in est:
        pn = str(p.get("part_number") or "")
        cg = (p.get("labour_estimate") or {}).get("costs_gbp") or {}
        if "diamond_polish" in cg:
            carriers.append(pn)

    print(f"\nParts with diamond_polish in costs_gbp: {carriers}\n")
    print(f"{'part':<16}{'finish (fuller record)':<34}{'verdict'}")
    print("-" * 92)
    for pn in carriers:
        fin = finish_by_pn.get(pn, "?")
        finu = fin.upper()
        is_powder = "POWDER" in finu
        is_raw = "RAW" in finu
        is_polish = any(k in finu for k in ("POLISH", "MIRROR", "DIAMOND", "BRUSHED", "GRAIN"))
        if is_polish:
            verdict = "GENUINE polish finish — KEEP diamond_polish"
        elif is_powder or is_raw:
            verdict = ">> SPURIOUS (finish is powder/raw) — SUPPRESS"
        else:
            verdict = "finish not polish — likely suppress (verify)"
        print(f"{pn:<16}{fin[:33]:<34}{verdict}")

    print("-" * 92)

    # safety scan: is there ANY part with a genuine polish finish we must protect?
    print("\nSAFETY SCAN — parts with a GENUINE polish/mirror finish (must NOT suppress):")
    any_polish = False
    for pn, fin in finish_by_pn.items():
        if any(k in fin.upper() for k in ("POLISH", "MIRROR", "DIAMOND", "BRUSHED", "GRAIN")):
            print(f"  {pn}: finish={fin!r}  ops={ops_by_pn.get(pn)}")
            any_polish = True
    if not any_polish:
        print("  none — no genuine polish finishes on this job; diamond_polish is spurious everywhere here.")

    print("\n" + "=" * 92)
    print("GATE RULE: suppress diamond_polish when finish is NOT a genuine polish finish")
    print("(powder/raw/other). Fail-safe: KEEP it when finish contains POLISH/MIRROR/DIAMOND.")
    print("Mirrors the powder gate exactly — same place in the labour loop.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python _probe_diamond_polish.py <json>"); sys.exit(1)
    main(sys.argv[1])
