#!/usr/bin/env python3
r"""
_probe_7670_powder.py  —  READ-ONLY.

THE BIGGEST LINE ON THE JOB IS NOW THE POWDER, AND IT IS WRONG TWICE OVER.

    engine:  TLP-J125-T RYOBI GREEN   qty 1     £7.72  ->  £8.03 with scrap
    Tim:     Powder171-Deep Orange    0.04 kg   £9.73/kg -> £0.40

    The job is called AEG **ORANGE** A4 Leaflet Holder.

Two independent errors, and they need separating before either is fixed:

  A. WRONG CODE.  Where did POWDER308 come from?
       - Is "POWDER308" actually printed on the drawing? If so, the drawing carries a
         stale/wrong code and this is a DESIGN finding.
       - Or did a text-scan recogniser reach for it? Then it is an ENGINE finding, and a
         serious one: a fuzzy code match that silently picks another customer's colour.
       - The UDEF catalogue then resolved POWDER308 -> RYOBI GREEN. If the code is right
         and the colour is wrong, the CATALOGUE is wrong.
     Three very different fixes. Do not guess which.

  B. WRONG QUANTITY.  The engine's own flag says it all:
       "qty defaulted to 1 (not in structured BOM) — estimator to confirm"
     One KILOGRAM of powder. Tim uses 0.04kg. That is 25x.
     And the workbook HAS a Powder Qty Calculator (m2/part -> kg/part) which computed
     0.00629 kg/part on 1310. On 7670 the Total Powder Per Unit cell reads 0 — because
     wire parts have no sheet area, so the calculator has nothing to work from.
     So the powder qty for a WIRE job cannot come from the sheet calculator at all.
     That is a real modelling gap, not a bug to patch over.

ALSO CONFIRMS THE THREE OPERATION DEFECTS, so the fix can be written once and correctly:

  C. Robomac is DOUBLE-BOOKED (my bug, from the grouping patch):
        Robomac — MILD STEEL      (001,002,003)  £0.33   <- injected group ("Robomac","","")
        Robomac — 4mm MILD STEEL  (001,002,003)  £0.33   <- natural group  ("Robomac","MILD_STEEL","4")

  D. Robomac/Spotweld are grouped PER JOB. Tim writes one row PER WIRE FORM:
        Robomac  main frame   100/hr    Robomac  back wire  450/hr    Robomac bottom 300/hr
        Spotweld buttweld     150/hr    Spotweld spotweld    45/hr
     Each wire form is a different bend program = a different setup.

  E. Weld (CO2) at 29/hr costs £6.18. Tim SPOTWELDS a wire frame: £1.61 across two rows.
     You do not CO2-weld 4mm wire.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_7670_powder.py
"""
from __future__ import annotations
import glob, json, os, re, sys

JSON_DIR = r"C:\ClaudeVision\output\json"
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
    cands = glob.glob(os.path.join(JSON_DIR, "*7670*.json"))
    if not cands:
        sys.exit("no 7670 JSON")
    path = max(cands, key=os.path.getmtime)
    data = json.load(open(path, "r", encoding="utf-8"))

    # ============ A. IS 'POWDER308' ON THE DRAWING? ============
    print("=" * 100)
    print("A. IS 'POWDER308' — OR ANY POWDER CODE — ACTUALLY PRINTED ON THE DRAWING?")
    print("=" * 100)
    found_any = False
    for pg in (data.get("pages") or []):
        num = pg.get("page_number") or pg.get("page")
        txt = page_text(pg)
        for m in re.finditer(r".{0,80}(POWDER\s*\d*|P/C|RAL\s*\d+|ORANGE|GREEN|TLP-?\w*).{0,80}",
                             txt, re.IGNORECASE):
            frag = " ".join(m.group(0).split())
            print(f"  page {num}: ...{frag}...")
            found_any = True
    if not found_any:
        print("  >>> NOTHING. No powder code, no colour, anywhere on any page. <<<")
        print("  >>> Then POWDER308 did NOT come from the drawing. The engine reached for it.")
        print("  >>> That is an ENGINE defect and a serious one: it invented a purchase line,")
        print("  >>> picked another customer's colour, and priced it at 25x the quantity.")

    # ============ B. WHERE DID THE POWDER PART RECORD COME FROM? ============
    print("\n" + "=" * 100)
    print("B. THE POWDER PART RECORD — provenance")
    print("=" * 100)
    for p in (data.get("parts") or []):
        blob = f"{p.get('part_number')} {p.get('description')}".upper()
        if "POWDER" not in blob and "TLP" not in blob and "RYOBI" not in blob:
            continue
        print(f"\n  part_number   {p.get('part_number')!r}")
        print(f"  description   {str(p.get('description'))[:80]}")
        print(f"  pages         {p.get('pages')!r}      <- empty = came from no page")
        print(f"  page_roles    {p.get('page_roles')!r}")
        for k in ("source", "cost_source", "supplier", "price_verified",
                  "_bought_in_from_text_scan", "unit_material_cost_gbp", "quantity",
                  "material_inherited_from"):
            print(f"  {k:<28} {p.get(k)!r}")
        for rf in (p.get("review_flags") or []):
            print(f"  review_flag   {str(rf)[:150]}")

    # ============ C. THE POWDER QUANTITY MODEL ============
    print("\n" + "=" * 100)
    print("C. THE QUANTITY — 1 kg vs Tim's 0.04 kg")
    print("=" * 100)
    print("  The workbook's Powder Qty Calculator derives kg from SHEET AREA (m2/part).")
    print("  A wire frame has no sheet area, so 'Total Powder Per Unit' reads 0 on this job.")
    print("  The engine then fell back to a DEFAULT of 1 unit and priced 1kg of powder.")
    print()
    print("  Tim computes powder for a wire frame anyway: 0.04kg @ £9.73 = £0.40.")
    print("  So there IS a rule for wire — it is just not the sheet-area rule.")
    print("  Surface area of the wire: pi x d x L")
    for pn, g, L, q in (("7670-01-001", 4.0, 975.4, 1),
                        ("7670-01-002", 4.0, 233.4, 2),
                        ("7670-01-003", 4.0, 424.8, 1)):
        area_m2 = 3.14159265 * (g / 1000.0) * (L / 1000.0) * q
        print(f"    {pn}  pi x {g}mm x {L}mm x{q} = {area_m2:.5f} m2")
    total = sum(3.14159265 * (4.0 / 1000.0) * (L / 1000.0) * q
                for L, q in ((975.4, 1), (233.4, 2), (424.8, 1)))
    print(f"    TOTAL wire surface area = {total:.5f} m2")
    print(f"    Tim's powder 0.04kg / {total:.5f} m2 = {0.04/total:.2f} kg/m2")
    print("    (1310 sheet parts imply a similar kg/m2 from the WB's own Qty-Per-Kilo table —")
    print("     worth checking whether ONE coverage rate serves both, which would make this")
    print("     a small fix rather than a new model.)")

    # ============ D/E. THE OPERATION DEFECTS ============
    print("\n" + "=" * 100)
    print("D. OPERATIONS ON EACH WIRE PART — what the engine costed")
    print("=" * 100)
    for pe in ((data.get("estimate_summary") or {}).get("part_estimates") or []):
        pn = str(pe.get("part_number") or "")
        if not pn.startswith("7670"):
            continue
        le = pe.get("labour_estimate") or {}
        me = pe.get("material_estimate") or {}
        print(f"\n  {pn}  {pe.get('description')}   qty={pe.get('quantity')}")
        print(f"      stock_form   {me.get('stock_form')!r}")
        print(f"      thickness_mm {pe.get('normalized_thickness_mm')!r}"
              f"   <- if still 4, the pricing record never got the 'diameter is not thickness' fix")
        print(f"      ops          {list((le.get('costs_gbp') or {}).keys())}")
        print(f"      costs_gbp    {le.get('costs_gbp')}")
    print("""
    TIM COSTS THIS JOB AS:
        Robomac  main frame   qty 1  100/hr  setup 15  £0.47
        Robomac  back wire    qty 2  450/hr  setup 15  £0.30
        Robomac  bottom frame qty 1  300/hr  setup 15  £0.26
        Spotweld buttweld     qty 1  150/hr  setup 30  £0.55
        Spotweld spotweld     qty 1   45/hr  setup 30  £1.06
        P.Coat                qty 1 1276/hr  setup 15  £1.92
        Asm/pack              qty 1  180/hr  setup  5  £0.21

    ENGINE COSTS IT AS:
        Robomac  x2 (DUPLICATED)  709/hr  £0.33 + £0.33
        Weld (CO2)                 29/hr  £6.18          <- should be SPOTWELD (£1.61)
        Asm/pack                   58/hr  £0.64
        (no P.Coat — assembly-level finish not modelled)

    THREE DISTINCT ENGINE DEFECTS:
      1. Robomac double-booked. My grouping patch injects a group keyed ("Robomac","","")
         while the natural op group keys ("Robomac","MILD_STEEL","4"). Two rows, same work.
      2. Robomac/Spotweld grouped PER JOB. Tim writes one row PER WIRE FORM — each form is
         a different bend program on the machine, so each is a genuine separate setup.
         My _ONE_ROW_PER_JOB call was wrong for these two ops.
      3. Wire is SPOTWELDED, not CO2-welded. 4mm wire frames go on the spot welder.
         'welding' on stock_form=wire must map to Spotweld.
""")

    print("""
====================================================================================
THE ORDER TO FIX, BY MONEY

    £8.03   powder      wrong colour AND 25x the quantity   <- biggest, needs section A
    £6.18   weld        should be Spotweld ~£1.61
    £0.33   Robomac     duplicate row
    £0.43   pack        setup 15 min vs Tim's 5
    ----
    Tim: £6.74.  Engine: £17.01.

The wire material is DONE: £0.31 vs Tim's £0.29, read from a PDF with no DXF.
Everything left is operations and the powder — none of it is geometry.
====================================================================================
""")


if __name__ == "__main__":
    main()
