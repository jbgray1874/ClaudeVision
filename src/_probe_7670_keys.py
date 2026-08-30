#!/usr/bin/env python3
r"""
_probe_7670_keys.py  —  READ-ONLY.

My last probe printed nothing, because it read summary["part_estimates"] and that list is
EMPTY on this job. I assumed the key without checking — twice. The workbook plainly HAS the
parts (£25.18 / £12.27 / £27.07 in the BOM), so they live somewhere else in the JSON.

Stop guessing. Walk the structure, find every dict that carries a price, and print where it
came from.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_7670_keys.py
"""
from __future__ import annotations
import glob, json, os, sys

JSON_DIR = r"C:\ClaudeVision\output\json"

# the three numbers we are hunting, from the populated workbook
HUNT = ("25.18", "12.27", "27.07", "7.72")


def walk(node, path=""):
    """Yield (path, dict) for every dict in the tree."""
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def main():
    cands = glob.glob(os.path.join(JSON_DIR, "*7670*.json"))
    if not cands:
        sys.exit("no 7670 JSON")
    path = max(cands, key=os.path.getmtime)
    data = json.load(open(path, "r", encoding="utf-8"))

    print("=" * 100)
    print(os.path.basename(path))
    print("=" * 100)

    # ---------- 1. top-level shape ----------
    print("\n--- 1. TOP-LEVEL KEYS ---")
    for k, v in data.items():
        if isinstance(v, list):
            print(f"  {k:<34} list[{len(v)}]")
        elif isinstance(v, dict):
            print(f"  {k:<34} dict({len(v)} keys)")
        else:
            print(f"  {k:<34} {str(v)[:56]}")

    # ---------- 2. where do the parts live? ----------
    print("\n--- 2. EVERY LIST THAT LOOKS LIKE PARTS ---")
    for p, node in walk(data):
        if not isinstance(node, dict):
            continue
        if node.get("part_number") and not p.endswith("]"):
            continue
    seen = set()
    for p, node in walk(data):
        if isinstance(node, dict) and "part_number" in node:
            base = p.rsplit("[", 1)[0]
            if base in seen:
                continue
            seen.add(base)
            print(f"  {base}")

    # ---------- 3. hunt the actual numbers ----------
    print("\n--- 3. WHERE DO £25.18 / £12.27 / £27.07 / £7.72 COME FROM? ---")
    for p, node in walk(data):
        if not isinstance(node, dict):
            continue
        blob = json.dumps(node, default=str)
        if not any(h in blob for h in HUNT):
            continue
        # only the leaf-most dicts that actually carry one of the numbers directly
        direct = [k for k, v in node.items()
                  if any(h in str(v) for h in HUNT) and not isinstance(v, (dict, list))]
        if not direct:
            continue
        print(f"\n  PATH: {p}")
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                _s = json.dumps(v, default=str)
                if len(_s) > 200:
                    _s = _s[:200] + " ..."
                print(f"      {k:<26} {_s}")
            else:
                print(f"      {k:<26} {str(v)[:90]}")

    print("""
====================================================================================
WHAT I AM LOOKING FOR

Any of these fields on the dicts above tells us where the price came from:

    cost_method            e.g. "bought_in_recognised_price:rag_fallback"
                                "web_indicative"
                                "sdi_bom_code_estimator_to_price"
    price_source           supplier_source / applied_basis / price_date
    cost_source, source    the recogniser that claimed the part
    rag_match / rag_score  a fuzzy history match, and how confident it was
    matched_description    WHAT it matched against — the smoking gun. If "MAIN FRAME"
                           matched some other job's frame, we will see it here.

Tim's total for all three wire forms is £0.29. The engine says £79.85. And a job called
AEG **ORANGE** got RYOBI **GREEN** powder at £7.72 against Tim's £0.40.

Once we know the source, the fix is specific rather than speculative — and the guard is
the same either way:

    A part with a JOB PART NUMBER and a DRAWING is FABRICATED. It is MADE, not BOUGHT.
    It must never be priced as a bought-in item. If geometry cannot cost it, say so
    loudly and leave it unpriced.
====================================================================================
""")


if __name__ == "__main__":
    main()
