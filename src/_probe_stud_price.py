#!/usr/bin/env python3
r"""
_probe_stud_price.py  —  READ-ONLY.

1310-02 STUD is 8mm dia x 65mm ROUND BAR, welded to the hook plate.

Tim costs it as WIRE:            material £0.04  +  Robomac £0.17
The engine now costs it as a BOUGHT-IN BOM line:   £6.69  (£6.96 with scrap)

That is ~170x over, and it is the entire material gap on 1310 (engine £10.60 vs Tim £6.90).

Note the number £6.69 is EXACTLY what the stud cost when it was (wrongly) read as 8mm-thick
SHEET STEEL last run. So the same figure has survived a reclassification from steel to
bought-in. That smells like a cost being carried forward rather than derived — we need to
know WHERE it comes from before we touch anything.

The engine has no wire / round-bar material class at all. The template's Wire block
(rows 53-60 in the widened sheet) has NEVER been populated on any job.

This probe answers three questions:
  1. What is the STUD's provenance? (source, cost_source, matched historical description,
     match score, confidence, price_verified)
  2. Is £6.69 a historical quote match, a catalogue price, a carried-over steel cost, or
     something derived?
  3. Does the drawing give us what a wire line needs — diameter and length?

Usage:
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_stud_price.py
"""
from __future__ import annotations
import json, glob, os, pprint

JSON_DIR = r"C:\ClaudeVision\output\json"

INTERESTING = (
    "part_number", "description", "source", "cost_source", "unit_cost_gbp", "costs_gbp",
    "price", "unit_price", "material", "material_class", "thickness_mm", "gauge",
    "diameter_mm", "length_mm", "page_roles", "confidence", "price_verified",
    "review_flag", "_headword", "_matched_historical_desc", "_match_score",
    "flat_pattern_detected", "dxf_augmented", "operations", "surface_finishes",
    "normalized_finish", "bought_in", "is_bought_in", "quantity", "qty",
)


def main():
    cands = glob.glob(os.path.join(JSON_DIR, "*1310*.json"))
    if not cands:
        raise SystemExit("no 1310 JSON found")
    path = max(cands, key=os.path.getmtime)
    print("=" * 96)
    print(os.path.basename(path))
    print("=" * 96)

    data = json.load(open(path, "r", encoding="utf-8"))
    parts = data.get("parts") or data.get("part_estimates") or []

    for p in parts:
        pn = str(p.get("part_number") or "")
        if "1310-02" not in pn and "STUD" not in str(p.get("description") or "").upper():
            continue

        print("\n--- FULL RECORD: 1310-02 STUD ---\n")
        for k in INTERESTING:
            if k in p:
                v = p[k]
                if isinstance(v, (dict, list)):
                    print(f"  {k}:")
                    pprint.pprint(v, indent=6, width=100)
                else:
                    print(f"  {k}: {v!r}")

        print("\n--- ANY OTHER KEYS ON THIS PART ---")
        others = [k for k in p if k not in INTERESTING]
        for k in sorted(others):
            v = p[k]
            s = str(v)
            print(f"  {k}: {s[:120]}{'...' if len(s) > 120 else ''}")

    # what does the drawing actually say about the stud?
    print("\n" + "=" * 96)
    print("DRAWING TEXT MENTIONING THE STUD / DIA / ROUND BAR")
    print("(a wire line needs: diameter + length. Does the drawing give us both?)")
    print("=" * 96)
    import re
    pat = re.compile(r"[^\n]{0,70}(?:STUD|\bDIA\b|Ø|ROUND\s*BAR|\bBAR\b|M8|8\s*mm)[^\n]{0,70}",
                     re.IGNORECASE)
    for pg in data.get("pages", []):
        num = pg.get("page_number") or pg.get("page") or "?"
        txt = ""
        for k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):
            if pg.get(k):
                txt += "\n" + str(pg[k])
        seen = set()
        hits = []
        for m in pat.finditer(txt):
            s = " ".join(m.group(0).split())
            if s.upper()[:60] in seen:
                continue
            seen.add(s.upper()[:60])
            hits.append(s)
        if hits:
            print(f"\n  page {num}:")
            for h in hits[:10]:
                print("   ", h)

    print("""
====================================================================================
WHAT WE ARE DECIDING

Tim treats an 8mm dia x 65mm round bar as WIRE:
    material  = length x (kg/m for 8mm dia) x £/tonne     -> £0.04
    labour    = Robomac (bar-cutting machine)             -> £0.17

The template already HAS a Wire block with the right formulas (M Per Tonne, Price Per M,
Kgs, gauge lookup) — rows 53-60 on the widened sheet. It has never been populated because
the engine has no wire/round-bar class: every fabricated part is forced into sheet steel
or, failing that, guessed as a bought-in.

If the £6.69 turns out to be a HISTORICAL QUOTE MATCH, that is the same circular-pricing
disease as the £105 phantom: a real quote line for a finished item being used to price a
raw component. If it is a CARRIED-OVER SHEET COST, it is a classification bug.

Either way we do not invent the price — the drawing gives diameter and length, and the
template gives the formula. That is a derivation, not a guess.
====================================================================================
""")


if __name__ == "__main__":
    main()
