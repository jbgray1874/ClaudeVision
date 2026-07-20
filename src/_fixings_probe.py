#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_fixings_probe.py — READ-ONLY diagnostic to scope the fixings-capture gap.

The engine found 3 fixings (all qty 1); Tim has ~6 at qty 2-4. This probe
answers TWO questions so we know what the real fix is:

  Q1: Where do the FOUND fixings come from — the drawing BOM, or the manual
      job_bought_in_materials.json (a hard-code we shouldn't lean on)?
  Q2: Are the MISSING fixings present in the raw extracted text (there-but-
      unparsed → structured-table parsing recovers them) or absent entirely
      (→ the BOM table isn't being extracted at all)?

It reads the job JSON + job_bought_in_materials.json ONLY. No changes.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _fixings_probe.py
"""
from __future__ import annotations
import io
import json
import os
import re

JSON_PATH = r"C:\ClaudeVision\output\json\12120-01-GA- DIGITAL TICKETING BRACKET.json"
BOUGHT_IN_JSON = "job_bought_in_materials.json"

# Terms for the fixings Tim has that the engine appears to miss (broad, case-insensitive).
MISSING_TERMS = [
    "THUMBSCREW", "THUMB SCREW", "BUTTON", "BUTTON HEAD", "KEYHOLE", "KEY HOLE",
    "CSK", "COUNTERSUNK", "GRUB", "SET SCREW", "SETSCREW", "M4", "M5", "M6",
    "SCREW", "BOLT", "WASHER", "STANDOFF", "SPACER", "RIVET",
]

# Terms for the fixings the engine DID find (to see how they appear in raw text).
FOUND_TERMS = ["PEM", "CLINCH", "KNURL", "STUD", "NUT", "KNOB"]


def load_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def walk_strings(obj, path=""):
    """Yield (json_path, string) for every string value in the structure."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk_strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk_strings(v, f"{path}[{i}]")


def main():
    if not os.path.exists(JSON_PATH):
        print("JSON not found:", JSON_PATH)
        return
    d = load_json(JSON_PATH)

    print("=" * 74)
    print("PART A — bought-in / fixing parts the engine produced (qty + source)")
    print("=" * 74)
    parts = d.get("parts", [])
    bought = [p for p in parts
              if str(p.get("part_number", "")).upper().startswith("BI-")
              or p.get("page_roles") == ["bought_in"]]
    if not bought:
        print("  (none found under 'parts' — checking other part containers)")
    for p in bought:
        print(f"  {str(p.get('part_number')):<22} qty={p.get('quantity')!s:<3} "
              f"src={p.get('source')!r} roles={p.get('page_roles')} "
              f"desc={p.get('description')!r}")
    # also show quantity provenance if present
    print("\n  Quantity provenance fields (if any) on the first bought-in part:")
    if bought:
        p0 = bought[0]
        for k in ("quantity", "quantity_source", "qty_source", "bom_qty",
                  "source", "review_flags"):
            if k in p0:
                print(f"    {k}: {p0.get(k)!r}")

    print()
    print("=" * 74)
    print("PART B — is job_bought_in_materials.json feeding these? (hard-code check)")
    print("=" * 74)
    if os.path.exists(BOUGHT_IN_JSON):
        try:
            bi = load_json(BOUGHT_IN_JSON)
        except Exception as e:
            print("  could not parse:", e)
            bi = None
        if bi is not None:
            # look for a 12120 entry
            txt = json.dumps(bi)
            has_12120 = "12120" in txt
            print(f"  file present. mentions '12120': {has_12120}")
            if isinstance(bi, dict):
                keys = list(bi.keys())
                print(f"  top-level keys: {keys[:20]}{' ...' if len(keys) > 20 else ''}")
                # print any 12120-keyed entry
                for k in keys:
                    if "12120" in str(k):
                        print(f"  ENTRY [{k}]:")
                        print("   ", json.dumps(bi[k])[:800])
            # do the found fixing codes appear here?
            for code in ("THREADEDPEMSTUD", "SELFCLINCHNUT", "KNURLEDKNOB", "SCREENCABLE"):
                print(f"  '{code}' in file: {code in txt}")
    else:
        print(f"  {BOUGHT_IN_JSON} NOT found in cwd — found fixings are NOT from it")
        print("  (so they came from drawing/BOM extraction, not the manual sheet)")

    print()
    print("=" * 74)
    print("PART C — where is the raw extracted text, and are MISSING fixings in it?")
    print("=" * 74)
    # find the largest string fields (likely raw page text / notes)
    all_strings = list(walk_strings(d))
    big = sorted(all_strings, key=lambda kv: len(kv[1]), reverse=True)[:8]
    print("  Largest text fields in the JSON (likely raw text / notes / BOM):")
    for pth, s in big:
        print(f"    [{len(s):>6} chars] {pth[:70]}")

    # concatenate ALL strings and search for terms (case-insensitive)
    haystack = "\n".join(s for _, s in all_strings).upper()

    print("\n  FOUND-fixing terms present in raw text (sanity — these SHOULD appear):")
    for t in FOUND_TERMS:
        n = haystack.count(t.upper())
        print(f"    {t:<12} : {n} occurrence(s)")

    print("\n  MISSING-fixing terms — are they in the raw text? (the key question):")
    for t in MISSING_TERMS:
        n = haystack.count(t.upper())
        mark = "  <-- PRESENT" if n else ""
        print(f"    {t:<14} : {n}{mark}")

    # show a snippet around any 'M4'/'THUMB'/'BUTTON'/'KEYHOLE' hit for context
    print("\n  Context snippets around key missing-fixing hits:")
    for term in ("THUMB", "BUTTON", "KEYHOLE", "M4"):
        idx = haystack.find(term)
        if idx != -1:
            lo, hi = max(0, idx - 60), min(len(haystack), idx + 60)
            snippet = haystack[lo:hi].replace("\n", " ")
            print(f"    '{term}': ...{snippet}...")
        else:
            print(f"    '{term}': (not found anywhere in extracted text)")

    print()
    print("=" * 74)
    print("INTERPRETATION")
    print("=" * 74)
    print("  - If MISSING terms (THUMBSCREW/BUTTON/KEYHOLE/M4) ARE present -> the data")
    print("    is in the extracted text but not PARSED into fixing rows+qty. Fix =")
    print("    structured BOM-table parsing (recover rows/qty). Viable, bounded.")
    print("  - If MISSING terms are ABSENT -> the BOM table text isn't being extracted")
    print("    at all. Fix = better table extraction/OCR (Azure/Textract) or SW BOM.")
    print("  - If found fixings' qty=1 with no qty_source -> qty is DEFAULTED, not read")
    print("    from a BOM column. Even the found ones have wrong quantities.")


if __name__ == "__main__":
    main()
