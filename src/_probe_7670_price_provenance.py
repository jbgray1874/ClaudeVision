#!/usr/bin/env python3
r"""
_probe_7670_price_provenance.py  —  READ-ONLY.

I said the engine "made up" £25.18 / £12.27 / £27.07 for the three wire forms. That was
sloppy — I do not know where those numbers came from, and there are four very different
possibilities, each with a different fix:

    1. RAG history lookup   — matched a description in the 1,982-job corpus
    2. web_ai_price_lookup  — the xAI LLM was asked to price a description
    3. BoughtInCatalogue    — matched a SKU
    4. geometry fallback    — costed as *something* (sheet?), badly

Same question for the powder line, which is arguably worse:

    TLP-J125-T  RYOBI GREEN  £7.72        <-- the job is AEG ORANGE
    Tim:        Powder171-Deep Orange £0.40  (0.04kg @ £9.73)

A wrong-customer, wrong-colour powder at 19x the price is not a rounding error. If that
came from a fuzzy history match on the word "powder", the matcher is unsafe. If it came
from the LLM, that is a different and more serious problem.

price_source metadata is written on every material_estimate. Read it.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_7670_price_provenance.py
"""
from __future__ import annotations
import glob, json, os, sys

JSON_DIR = r"C:\ClaudeVision\output\json"

TIM = {
    "7670-01-001": ("MAIN FRAME",   "4mm wire, 976mm  -> £0.15 material + Robomac £0.47"),
    "7670-01-002": ("HOOK",         "4mm wire, 234mm x2 -> £0.07 material + Robomac £0.30"),
    "7670-01-003": ("BOTTOM FRAME", "4mm wire, 425mm  -> £0.07 material + Robomac £0.26"),
}


def main():
    cands = glob.glob(os.path.join(JSON_DIR, "*7670*.json"))
    if not cands:
        sys.exit("no 7670 JSON")
    path = max(cands, key=os.path.getmtime)
    print("=" * 100)
    print(os.path.basename(path))
    print("Tim's TOTAL material for all three wire parts: £0.29.  Engine: £79.85.")
    print("=" * 100)

    data = json.load(open(path, "r", encoding="utf-8"))
    pes = data.get("part_estimates") or []

    for pe in pes:
        pn = str(pe.get("part_number") or "")
        me = pe.get("material_estimate") or {}
        ps = me.get("price_source") or {}
        desc = str(pe.get("description") or "")

        print("\n" + "-" * 100)
        print(f"  {pn}  {desc[:60]}")
        if pn in TIM:
            print(f"  TIM: {TIM[pn][1]}")
        print("-" * 100)

        print(f"    unit_material_cost_gbp   {me.get('unit_material_cost_gbp')!r}")
        print(f"    cost_method              {me.get('cost_method')!r}")
        print(f"    stock_form               {me.get('stock_form')!r}")
        print(f"    normalized_material      {pe.get('normalized_material')!r}")
        print(f"    normalized_thickness_mm  {pe.get('normalized_thickness_mm')!r}")

        print("\n    --- price_source (THE ANSWER) ---")
        if not ps:
            print("      (none — the price came from somewhere that writes no provenance.")
            print("       That is itself a finding: an unattributable price.)")
        for k, v in ps.items():
            print(f"      {k:<26} {str(v)[:80]}")

        # any other pricing breadcrumbs on the record
        for k in ("cost_source", "source", "price_verified", "supplier",
                  "rag_match", "rag_score", "matched_description", "llm_price",
                  "catalogue_sku", "review_flags", "risk_flags"):
            if pe.get(k) not in (None, "", [], {}):
                print(f"    {k:<26} {str(pe.get(k))[:90]}")

    # ---- the powder line ----
    print("\n" + "=" * 100)
    print("  THE POWDER LINE — engine picked RYOBI GREEN for an AEG ORANGE job")
    print("=" * 100)
    for pe in pes:
        blob = (str(pe.get("part_number") or "") + " " + str(pe.get("description") or "")).upper()
        if "POWDER" in blob or "TLP" in blob or "THERMASET" in blob or "RYOBI" in blob:
            me = pe.get("material_estimate") or {}
            ps = me.get("price_source") or {}
            print(f"\n  part_number  {pe.get('part_number')!r}")
            print(f"  description  {str(pe.get('description'))[:90]}")
            print(f"  unit price   {me.get('unit_material_cost_gbp')!r}   (Tim: £9.73/kg x 0.04kg = £0.40)")
            print(f"  cost_method  {me.get('cost_method')!r}")
            for k, v in ps.items():
                print(f"    {k:<26} {str(v)[:80]}")
            for k in ("cost_source", "source", "supplier", "rag_match", "matched_description"):
                if pe.get(k):
                    print(f"    {k:<26} {str(pe.get(k))[:90]}")

    print("""

====================================================================================
HOW TO READ THIS — each source implies a DIFFERENT fix

  cost_method / price_source says RAG or history
      -> a fuzzy description match pulled another job's part. The matcher is scoring
         "MAIN FRAME" against unrelated frames and returning a price with no sanity
         check. Fix: a fabricated part with a JOB PART NUMBER must never be priced from
         history as if it were a purchase.

  cost_method / price_source says web_ai / LLM
      -> the LLM was handed "MAIN FRAME" and invented a plausible number. Worse, because
         it will be confidently different every run. Fix: never send a job part number to
         a price LLM. Those parts are MADE, not bought.

  cost_method says a geometry method (sheet/blank)
      -> it costed a wire form as sheet steel, like the 1310 stud. Same root cause,
         different symptom.

  price_source EMPTY
      -> an unattributable price. On its own that is a reportable defect: every number in
         an estimate must be able to say where it came from.

WHATEVER THE ANSWER, THE GUARD IS THE SAME AND IT IS SIMPLE:

    A part with a JOB PART NUMBER and a DRAWING is FABRICATED.
    It is MADE, not BOUGHT. It must NEVER be priced as a bought-in item.
    If the geometry route cannot cost it, the engine says so LOUDLY and leaves it
    unpriced — an honest gap the estimator can fill.

That single rule turns £94.49 into "three parts I cannot cost, and here is why", which is
a genuinely useful output. The credibility gate already refused to publish this (9%), so
nothing escaped — but the gate is the last line of defence, not the first.
====================================================================================
""")


if __name__ == "__main__":
    main()
