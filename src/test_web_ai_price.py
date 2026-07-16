#!/usr/bin/env python3
"""Standalone test harness for web_ai_price_lookup.lookup_web_ai_price.

Exercises the two price-lookup stages — web (SerpAPI catalogue search) and the
LLM market estimate — against a handful of representative SDI parts, and prints
exactly what each stage returns. It degrades gracefully when a provider key is
missing or out of credit: lookup_web_ai_price already catches those and returns
{"found": False}, so the only effect is that the line would fall to UNPRICED.
Nothing here invents a price.

Run from the same folder as web_ai_price_lookup.py (e.g. C:\\ClaudeVision\\src):

    python test_web_ai_price.py                # web + LLM (each stage fires only if its key is set)
    python test_web_ai_price.py --no-llm       # web only — test SerpAPI in isolation (no LLM key needed)
    python test_web_ai_price.py --no-web       # LLM only
    python test_web_ai_price.py --only loom    # run a single sample by name
    python test_web_ai_price.py --json         # dump the full raw return dict per part
"""
import argparse
import json
import os
import sys
import traceback
import config
import os
print(f"XAI_API_KEY      set : {bool(os.environ.get('XAI_API_KEY'))}")


try:
    from web_ai_price_lookup import lookup_web_ai_price
except Exception as exc:  # import-time failure (wrong cwd, missing deps)
    print(f"Could not import lookup_web_ai_price: {exc}")
    print("Run this from the folder containing web_ai_price_lookup.py (e.g. src\\).")
    sys.exit(1)


# Representative SDI parts. Same dict ("spec") shape that
# pricing_service._get_web_ai_fallback builds for the live fallback hop.
# Extra keys (colour/length/width/weight/operations) are harmless — the lookup
# only reads material/description/thickness_mm/part_code/finish/quantity.
SAMPLES = {
    "loom": {
        "description": "Wiring loom assembly — LED bay harness, 4-way, bespoke",
        "part_code": "ELECTRICS", "material": "", "quantity": 1,
        "finish": "", "thickness_mm": None,
    },
    "rivet": {
        "description": "Blind rivet, dome head, 4.8 x 12mm, aluminium body / steel mandrel",
        "part_code": "FIXING125", "material": "Aluminium", "quantity": 100,
        "finish": "", "thickness_mm": None,
    },
    "nutsert": {
        "description": "Rivet nut / threaded insert, M5, steel, knurled body",
        "part_code": "FIXING236", "material": "Steel", "quantity": 50,
        "finish": "Zinc", "thickness_mm": None,
    },
    "tube": {
        "description": "Mild steel ERW box section, 40 x 40 x 2mm, cut to length",
        "part_code": "TUBE0070", "material": "Mild Steel", "quantity": 1,
        "finish": "", "thickness_mm": 2.0,
    },
    "sheet": {
        "description": "Laser-cut + folded bracket, 2mm mild steel, powder coated",
        "part_code": "1448-01", "material": "Mild Steel", "quantity": 4,
        "finish": "Powder Coat", "thickness_mm": 2.0,
    },
}

# Fields we surface (in this order); anything else lands in "(other)".
FIELDS = [
    "found", "price_gbp", "confidence", "source_type", "price_basis",
    "supplier_name", "price_date", "web_query",
    "low_estimate_gbp", "high_estimate_gbp", "verify_against", "review_reason", "error",
]


def run_one(name, spec, enable_web, enable_llm, dump_json):
    print("=" * 80)
    print(f"PART: {name}")
    print(f"  spec   -> code={spec.get('part_code')!r}  material={spec.get('material')!r}  "
          f"qty={spec.get('quantity')}  desc={spec.get('description')!r}")
    print(f"  stages -> web_search={enable_web}  llm_estimate={enable_llm}")
    try:
        res = lookup_web_ai_price(spec, enable_web_search=enable_web, enable_llm_estimate=enable_llm)
    except Exception as exc:
        # Should not happen — the lookup is meant to swallow provider errors. If it
        # does, that's a finding (the live fallback hop also wraps this in try/except).
        print(f"  !! lookup RAISED (degrade-on-error is built in, so this is a finding): {exc}")
        traceback.print_exc()
        return None
    if not isinstance(res, dict):
        print(f"  !! unexpected return type {type(res).__name__}: {res!r}")
        return None

    if dump_json:
        print("  raw:", json.dumps(res, default=str, indent=2))
    else:
        for k in FIELDS:
            if k in res and res[k] not in (None, ""):
                print(f"    {k:18}: {res[k]}")
        extra = {k: v for k, v in res.items() if k not in FIELDS}
        if extra:
            print(f"    {'(other)':18}: {json.dumps(extra, default=str)[:240]}")

    if res.get("found"):
        verdict = f"PRICED  £{float(res.get('price_gbp') or 0):.2f}  via {res.get('source_type') or '?'}"
    else:
        verdict = "NO PRICE  ->  line falls to UNPRICED (flagged for review)"
    print(f"    {'VERDICT':18}: {verdict}")
    return res


def main():
    ap = argparse.ArgumentParser(description="Test lookup_web_ai_price on representative SDI parts.")
    ap.add_argument("--no-web", action="store_true", help="disable the web (SerpAPI) stage")
    ap.add_argument("--no-llm", action="store_true", help="disable the LLM estimate stage")
    ap.add_argument("--only", help="run one sample by name: " + ", ".join(SAMPLES))
    ap.add_argument("--json", action="store_true", help="dump the full raw return dict per part")
    args = ap.parse_args()

    enable_web = not args.no_web
    enable_llm = not args.no_llm

    print("web_ai_price_lookup — test harness")
    print(f"  SERPAPI_API_KEY  set : {bool(os.environ.get('SERPAPI_API_KEY'))}   (web search / catalogue)")
    print(f"  XAI_API_KEY      set : {bool(os.environ.get('XAI_API_KEY'))}   (LLM estimate — xai)")
    print(f"  ANTHROPIC_API_KEY set: {bool(os.environ.get('ANTHROPIC_API_KEY'))}   (LLM estimate — anthropic)")
    print("  A stage with no key simply reports 'unavailable' and is skipped — that is expected.")
    print()

    if args.only and args.only not in SAMPLES:
        print(f"unknown sample {args.only!r}; choices: {', '.join(SAMPLES)}")
        return
    items = ([(args.only, SAMPLES[args.only])] if args.only else list(SAMPLES.items()))

    found = 0
    for name, spec in items:
        res = run_one(name, spec, enable_web, enable_llm, args.json)
        if res and res.get("found"):
            found += 1

    print("=" * 80)
    print(f"done — {found}/{len(items)} sample(s) returned a price.")
    print("'found: False' is the correct, safe outcome when a provider is missing or out of")
    print("credit: the engine flags the line UNPRICED and a human prices it. No price is invented.")


if __name__ == "__main__":
    main()
