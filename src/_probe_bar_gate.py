#!/usr/bin/env python3
r"""
_probe_bar_gate.py  —  READ-ONLY.

The wire/bar patch did NOT fire, and the stud got MORE expensive:

    before patch:  1310-02 STUD in BOM @ £6.69   (Tim: £0.04 wire + £0.17 Robomac)
    after  patch:  1310-02 STUD in BOM @ £25.77
    wire block:    EMPTY
    Robomac:       absent
    unit cost:     £10.60 -> £31.93   (Tim: £6.90)

So the gate never set stock_form='wire', but SOMETHING changed the part's cost. That is the
worst combination: half-applied. Find out exactly where it broke before touching anything.

THREE HYPOTHESES, in order of suspicion:

  H1. part["pages"] IS NOT POPULATED YET at document_builder.py:~823 where the gate runs.
      The final JSON shows pages:[4], but that is the FINISHED record. If the key is empty
      at gate time, _own_pages is empty, the page-text lookup returns "", the regex never
      sees "1 1 8mm DIA 65", and the gate silently no-ops.

  H2. The regex does not match the real page-4 text (spacing/ordering differs from what the
      earlier probe printed).

  H3. The gate DID fire and cleared normalized_thickness_mm, but stock_form never became
      'wire' (e.g. material_estimate is rebuilt downstream), so the part lost its thickness
      AND missed the wire route -> fell through to BOM with a worse cost. This would explain
      the price going UP.

Usage:
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_bar_gate.py
"""
from __future__ import annotations
import json, glob, os, re, sys

JSON_DIR = r"C:\ClaudeVision\output\json"

# the exact regex the patch installed
_WIRE_BAR_SCHED_RE = re.compile(
    r"(?:^|\s)(\d{1,2})\s+(\d{1,3})\s+(\d{1,2}\.?\d*)\s*mm\s*DIA\s+(\d{2,5}\.?\d*)(?:\s|$)",
    re.IGNORECASE,
)

TEXT_KEYS = ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview")


def page_text(pg):
    out = []
    rt = pg.get("region_text") or {}
    if isinstance(rt, dict):
        out += [str(v) for v in rt.values() if v]
    for k in TEXT_KEYS:
        if pg.get(k):
            out.append(str(pg[k]))
    return " ".join(out)


def main():
    cands = glob.glob(os.path.join(JSON_DIR, "*1310*.json"))
    if not cands:
        sys.exit("no 1310 JSON")
    path = max(cands, key=os.path.getmtime)
    print("=" * 96)
    print(os.path.basename(path))
    print("=" * 96)

    data = json.load(open(path, "r", encoding="utf-8"))

    # ---------- H3: did the gate leave its fingerprints? ----------
    print("\n--- H3: DID THE GATE FIRE AT ALL? ---")
    parts = data.get("parts") or data.get("part_estimates") or []
    stud = None
    for p in parts:
        if "1310-02" in str(p.get("part_number") or ""):
            stud = p
            break
    if not stud:
        print("  !! 1310-02 not found in parts")
    else:
        for k in ("_bar_recognised", "wire_gauge_mm", "wire_length_mm", "bar_schedule",
                  "normalized_thickness_mm", "_wire_part_override", "flat_pattern_detected",
                  "pages", "operations", "textual_operations"):
            print(f"  {k:<26} {stud.get(k, '<absent>')!r}")
        me = stud.get("material_estimate") or {}
        print(f"  material_estimate.stock_form     {me.get('stock_form', '<absent>')!r}")
        print(f"  material_estimate.wire_gauge_mm  {me.get('wire_gauge_mm', '<absent>')!r}")
        print(f"  material_estimate.wire_length_mm {me.get('wire_length_mm', '<absent>')!r}")
        print(f"  unit_cost_gbp                    {stud.get('unit_cost_gbp', '<absent>')!r}")
        print(f"  extended_total_cost_gbp          {stud.get('extended_total_cost_gbp', '<absent>')!r}")
        print("\n  full material_estimate:")
        for k, v in (me or {}).items():
            print(f"      {k}: {str(v)[:90]}")

        print("""
  READ:
    _bar_recognised absent + thickness still 8  -> gate NEVER RAN  (H1 or H2)
    _bar_recognised True   + stock_form != wire -> gate ran, ROUTING failed (H3)
    thickness None + stock_form != wire         -> HALF-APPLIED: the £25.77. Worst case.
""")

    # ---------- H2: does the regex match the real page text? ----------
    print("\n--- H2: DOES THE REGEX MATCH THE ACTUAL PAGE TEXT? ---")
    for pg in data.get("pages", []):
        num = pg.get("page_number") or pg.get("page")
        txt = page_text(pg)
        hits = _WIRE_BAR_SCHED_RE.findall(txt)
        if "DIA" in txt.upper():
            print(f"\n  page {num}: contains 'DIA'")
            # show the neighbourhood
            for m in re.finditer(r".{0,50}DIA.{0,50}", txt, re.IGNORECASE):
                print(f"      ...{' '.join(m.group(0).split())}...")
            print(f"      regex hits: {hits if hits else 'NONE  <-- regex does not match'}")

    # ---------- H1: is 'pages' set, and does it line up? ----------
    print("\n--- H1: PART 'pages' vs SUMMARY page numbers ---")
    print(f"  summary page numbers: {[pg.get('page_number') or pg.get('page') for pg in data.get('pages', [])]}")
    for p in parts:
        pn = str(p.get("part_number") or "")
        print(f"  {pn:<16} pages={p.get('pages', '<absent>')!r}  "
              f"types={[type(x).__name__ for x in (p.get('pages') or [])]}")

    print("""
====================================================================================
NOTE THE PRICE MOVED THE WRONG WAY: £6.69 -> £25.77.

A gate that does not fire should have left the part EXACTLY as it was. It did not. So
either the gate half-ran, or clearing normalized_thickness_mm changed a downstream cost
path while the part still routed to BOM.

Either way: do not layer another patch on top. If this probe shows the gate half-applied,
REVERT first —

    Copy-Item C:\\ClaudeVision\\src\\document_builder.py.bak_wirebar_20260713_150409 `
              C:\\ClaudeVision\\src\\document_builder.py -Force
    Copy-Item C:\\ClaudeVision\\src\\wb_populate.py.bak_wirebar_20260713_150409 `
              C:\\ClaudeVision\\src\\wb_populate.py -Force

— get back to the known £10.60, and re-cut the patch against what this probe reveals.
====================================================================================
""")


if __name__ == "__main__":
    main()
