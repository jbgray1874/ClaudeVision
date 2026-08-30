"""
audit_material_provenance.py — quantify how often a part's material comes from
its OWN page (trustworthy) versus a downstream fallback (the silent-luck case
where the title-block link failed and something else filled it in).

Reads engine scan JSONs (the ones under output/json that carry
manufacturing_writeup.parts). For each part it classifies the material source:

    direct    : materials[] populated -> assigned from the part's own
                detail / component page (trustworthy, has provenance).
    fallback  : materials[] empty but normalized_material set -> the part's
                page never linked; material was filled downstream by luck.
    blank     : no material at all.

Usage:
    python audit_material_provenance.py --in output\\json
    python audit_material_provenance.py --in output\\json\\SOME_SCAN.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _classify(part: Dict[str, Any]) -> str:
    has_mat = bool(part.get("normalized_material"))
    direct = bool(part.get("materials"))
    if direct:
        return "direct"
    if has_mat:
        return "fallback"
    return "blank"


def audit_one(scan: Dict[str, Any]) -> Dict[str, Any]:
    parts = (scan.get("manufacturing_writeup") or {}).get("parts") or scan.get("parts") or []
    counts = {"direct": 0, "fallback": 0, "blank": 0}
    fallback_parts: List[str] = []
    for p in parts:
        kind = _classify(p)
        counts[kind] += 1
        if kind == "fallback":
            fallback_parts.append(f"{p.get('part_number')}={p.get('normalized_material')} ({p.get('description')})")
    return {"n_parts": len(parts), "counts": counts, "fallback_parts": fallback_parts}


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Audit part material provenance in scan JSONs")
    ap.add_argument("--in", dest="inp", required=True, help="A scan JSON or a folder of them")
    ap.add_argument("--show-parts", action="store_true", help="List the fallback-sourced parts per job")
    args = ap.parse_args()

    inp = Path(args.inp)
    files = [inp] if inp.is_file() else sorted(inp.glob("*.json"))

    tot = {"direct": 0, "fallback": 0, "blank": 0}
    jobs = parts_total = 0
    for f in files:
        try:
            scan = _load(f)
        except Exception:
            continue
        if not ((scan.get("manufacturing_writeup") or {}).get("parts") or scan.get("parts")):
            continue  # not a scan summary
        r = audit_one(scan)
        jobs += 1
        parts_total += r["n_parts"]
        for k in tot:
            tot[k] += r["counts"][k]
        fb = r["counts"]["fallback"]
        pct = (fb / r["n_parts"] * 100) if r["n_parts"] else 0
        print(f"{f.name[:55]:55} parts={r['n_parts']:3}  "
              f"direct={r['counts']['direct']:3}  fallback={fb:3} ({pct:4.0f}%)  blank={r['counts']['blank']:3}")
        if args.show_parts and r["fallback_parts"]:
            for fp in r["fallback_parts"]:
                print(f"      fallback: {fp}")

    if jobs:
        fb_pct = tot["fallback"] / parts_total * 100 if parts_total else 0
        bl_pct = tot["blank"] / parts_total * 100 if parts_total else 0
        print(f"\nAcross {jobs} job(s), {parts_total} parts: "
              f"direct {tot['direct']} ({tot['direct']/parts_total*100:.0f}%), "
              f"fallback {tot['fallback']} ({fb_pct:.0f}%), "
              f"blank {tot['blank']} ({bl_pct:.0f}%)")
        print("fallback% = how often a part's material was NOT sourced from its own page "
              "(linking failed; filled downstream). High % = the problem is common; "
              "parity vs manual estimates then tells us how often it's actually WRONG.")
    else:
        print("No scan summaries found.")
