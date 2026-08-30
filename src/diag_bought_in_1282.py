#!/usr/bin/env python3
"""
diag_bought_in_1282.py  --  §5 "measure before building" diagnostic.

READ-ONLY. Touches no DB, no src, writes nothing. It answers the one question
that scopes the bought-in BOM re-sourcing fix:

    Is the fix "price them" (engine already CAPTURES the bought-in lines from
    the drawing, they just price wrong / to £0) or "capture + price them"
    (engine never produced the line in the first place)?

It does that by comparing, for one job:
  • LEFT  = what the engine's run actually produced  (the output JSON)
  • RIGHT = Tim's manual-sheet baseline             (job_bought_in_materials.json)

Run it on the REAL output, e.g.:

    python diag_bought_in_1282.py ^
        --job "C:\\ClaudeVision\\output\\json\\1282 - Milwaukee Wall Bay.json" ^
        --tim "C:\\ClaudeVision\\src\\job_bought_in_materials.json" ^
        --drawing 1282

Then paste the printed REPORT back into the chat and we build the fix from
real numbers, not assumptions.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


# ──────────────────────────────────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────────────────────────────────
def load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8-sig") as fh:  # utf-8-sig tolerates BOM
        return json.load(fh)


def find_parts(doc: Any) -> List[Dict[str, Any]]:
    """The engine's part list lives under manufacturing_writeup.parts; fall back
    through the other shapes the pipeline has used at different stages."""
    if not isinstance(doc, dict):
        return []
    for path in (
        ("manufacturing_writeup", "parts"),
        ("parts",),
        ("manufacturing_writeup", "writeup", "parts"),
    ):
        node: Any = doc
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and isinstance(node, list) and node:
            return node
    return []


def find_estimate_lookup(doc: Any) -> Dict[str, Dict[str, Any]]:
    """estimate_summary.part_estimates, keyed by part_number, holds the priced
    result (material/process/labour). Defensive against shape drift."""
    if not isinstance(doc, dict):
        return {}
    for path in (
        ("estimate_summary", "part_estimates"),
        ("estimate", "part_estimates"),
        ("part_estimates",),
    ):
        node: Any = doc
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and isinstance(node, list):
            return {
                str(e.get("part_number", "")).strip().upper(): e
                for e in node
                if isinstance(e, dict) and e.get("part_number")
            }
    return {}


# ──────────────────────────────────────────────────────────────────────────
# Pricing extraction — walk the estimate for anything cost/price/source-ish
# rather than hard-coding one nested path (the engine has several).
# ──────────────────────────────────────────────────────────────────────────
_COST_KEYS = re.compile(r"(cost|price).*gbp$|^unit_cost$|^extended|system_unit_cost|applied_unit_cost", re.I)
_SOURCE_KEYS = re.compile(r"(price_)?source(_name|_key)?$|^source$|pricing_source", re.I)
_CONF_KEYS = re.compile(r"confidence|review_flag|price_verified|verified", re.I)


def _collect(node: Any, matcher: re.Pattern, out: Dict[str, Any], prefix: str = "") -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            key = f"{prefix}{k}"
            if isinstance(v, (dict, list)):
                if matcher.search(str(k)) and not isinstance(v, list):
                    # a 'price_source' object — keep a compact form
                    out[key] = _compact(v)
                _collect(v, matcher, out, key + ".")
            elif matcher.search(str(k)) and v not in (None, "", [], {}):
                out[key] = v
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _collect(v, matcher, out, f"{prefix}{i}.")


def _compact(v: Any) -> Any:
    if isinstance(v, dict):
        keep = {}
        for k in ("source", "source_name", "source_key", "type", "applied", "basis"):
            if k in v:
                keep[k] = v[k]
        return keep or {k: _compact(x) for k, x in list(v.items())[:4]}
    return v


def pricing_view(estimate: Dict[str, Any]) -> Dict[str, Any]:
    costs: Dict[str, Any] = {}
    sources: Dict[str, Any] = {}
    conf: Dict[str, Any] = {}
    _collect(estimate, _COST_KEYS, costs)
    _collect(estimate, _SOURCE_KEYS, sources)
    _collect(estimate, _CONF_KEYS, conf)
    return {"costs": costs, "sources": sources, "confidence": conf}


def headline_cost(costs: Dict[str, Any]) -> Optional[float]:
    """Pick the most representative per-part cost we can find."""
    for prefer in ("system_unit_cost", "applied_unit_cost"):
        for k, v in costs.items():
            if k.endswith(prefer) and isinstance(v, (int, float)):
                return float(v)
    for hint in ("cost_per_part_gbp", "unit_material_cost_gbp", "unit_cost"):
        for k, v in costs.items():
            if k.endswith(hint) and isinstance(v, (int, float)):
                return float(v)
    nums = [v for v in costs.values() if isinstance(v, (int, float))]
    return float(nums[0]) if nums else None


# ──────────────────────────────────────────────────────────────────────────
# Matching engine parts <-> Tim's lines
# ──────────────────────────────────────────────────────────────────────────
def norm(s: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


_CODE_RE = re.compile(r"^([A-Z]+\d+[A-Z]?|FIXING\d+|SLOTTEDTUBE\d+|SUBPLAS\d+|MINIFIX)", re.I)


def lead_code(desc: str) -> str:
    """Pull the leading code token out of a Tim description like
    'FIXING125-M8 x 25mm GUIDES' -> 'FIXING125', 'ELECTRICS - 50cm LOOM' -> 'ELECTRICS'."""
    head = re.split(r"[-\s]", str(desc or "").strip(), maxsplit=1)[0]
    m = _CODE_RE.match(str(desc or "").strip())
    return (m.group(1) if m else head).upper()


def tim_key(line: Dict[str, Any]) -> str:
    return norm(line.get("part_code") or lead_code(line.get("description", "")))


def match_engine_part(tim_line: Dict[str, Any], parts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    tkey = tim_key(tim_line)
    tdesc = norm(tim_line.get("description"))
    if not tkey and not tdesc:
        return None
    for p in parts:
        pn = norm(p.get("part_number"))
        pdesc = norm(p.get("description"))
        if tkey and (tkey == pn or (len(tkey) >= 4 and (tkey in pn or tkey in pdesc))):
            return p
        if tdesc and pdesc and (tdesc in pdesc or pdesc in tdesc) and len(tdesc) >= 6:
            return p
    return None


# ──────────────────────────────────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Scope the §5 bought-in BOM fix.")
    ap.add_argument("--job", required=True, help="Path to the engine output JSON for the job.")
    ap.add_argument("--tim", required=True, help="Path to job_bought_in_materials.json (Tim baseline).")
    ap.add_argument("--drawing", default="1282", help="Drawing number key in the Tim JSON (default 1282).")
    args = ap.parse_args()

    try:
        doc = load_json(args.job)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR loading job JSON: {exc}", file=sys.stderr)
        return 2
    try:
        tim = load_json(args.tim)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR loading Tim JSON: {exc}", file=sys.stderr)
        return 2

    parts = find_parts(doc)
    est_lookup = find_estimate_lookup(doc)
    tim_lines = (((tim or {}).get("by_drawing") or {}).get(str(args.drawing)) or {}).get("lines") or []

    def roles(p: Dict[str, Any]) -> List[str]:
        return [str(r).lower() for r in (p.get("page_roles") or [])]

    bought_in = [p for p in parts if "bought_in" in roles(p)]
    bom_only = [p for p in parts if "bom_only" in roles(p) and "bought_in" not in roles(p)]

    line = "=" * 78
    print(line)
    print(f" §5 BOUGHT-IN DIAGNOSTIC  —  job: {doc.get('source_file', args.job)}")
    print(line)
    print(f" parts in writeup ............ {len(parts)}")
    print(f" page_roles == bought_in ..... {len(bought_in)}")
    print(f" page_roles == bom_only ...... {len(bom_only)}")
    print(f" Tim baseline lines (dwg {args.drawing}) ... {len(tim_lines)}")
    print()

    # --- LEFT: what the engine captured, and how each priced ---------------
    print("-" * 78)
    print(" ENGINE bought_in / bom_only parts (LEFT side of the gap)")
    print("-" * 78)
    if not bought_in and not bom_only:
        print("  (none captured — this alone proves 'capture' is the missing half)")
    for p in bought_in + bom_only:
        pn = p.get("part_number")
        est = est_lookup.get(str(pn).strip().upper(), {})
        pv = pricing_view(est)
        cost = headline_cost(pv["costs"])
        src = "; ".join(f"{k}={v}" for k, v in pv["sources"].items()) or "—"
        print(f"  [{','.join(roles(p))}] {pn!s:<22} qty={p.get('quantity')!s:<4} "
              f"src={p.get('source','-')}")
        print(f"      desc : {str(p.get('description') or '')[:70]}")
        print(f"      cost : {('£%.4f' % cost) if cost is not None else 'NONE / £0'}")
        print(f"      price_source : {src[:120]}")
        if pv["confidence"]:
            print(f"      conf : {pv['confidence']}")
    print()

    # --- RIGHT: Tim's lines, matched or missing ----------------------------
    print("-" * 78)
    print(" TIM baseline lines — recovered by the drawing scan?  (RIGHT side)")
    print("-" * 78)
    recovered = 0
    missing: List[Dict[str, Any]] = []
    for tl in tim_lines:
        m = match_engine_part(tl, parts)
        tag = "RECOVERED" if m else "MISSING  "
        if m:
            recovered += 1
        else:
            missing.append(tl)
        via = f"  ->  engine PN {m.get('part_number')}" if m else ""
        print(f"  [{tag}] £{tl.get('unit_price_gbp')!s:<8} x{tl.get('qty_per_unit')!s:<4} "
              f"{str(tl.get('description') or '')[:46]}{via}")
    print()

    # --- VERDICT -----------------------------------------------------------
    print(line)
    n = len(tim_lines) or 1
    print(f" VERDICT:  recovered {recovered}/{len(tim_lines)} of Tim's lines "
          f"({100*recovered//n}%)")
    if missing:
        print(f"           {len(missing)} line(s) NEVER produced by the drawing scan:")
        for tl in missing:
            print(f"             - {tl.get('description')}")
        print()
        print("   => This is a CAPTURE + PRICE fix (bigger). The drawing scan must")
        print("      first PRODUCE these lines (widen bom_rows / bought-in capture to")
        print("      description-only & non-hyphenated rows, incl. NOTES-zone items),")
        print("      THEN price them via the catalogue path, THEN remove the")
        print("      xlsx_output _load_bought_in_for() override (last, once proven).")
    else:
        print("   => Every Tim line is already CAPTURED. This is a PRICE-ONLY fix")
        print("      (smaller): route the captured bought_in parts through the")
        print("      catalogue pricing path so they stop pricing to £0, then drop")
        print("      the xlsx_output override.")
    # parts captured but with no / zero price are the other half of the picture
    unpriced = []
    for p in bought_in:
        est = est_lookup.get(str(p.get("part_number")).strip().upper(), {})
        c = headline_cost(pricing_view(est)["costs"])
        if not c:
            unpriced.append(p.get("part_number"))
    if unpriced:
        print(f"   NOTE: captured-but-unpriced bought_in parts: {unpriced}")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
