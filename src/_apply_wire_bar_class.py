#!/usr/bin/env python3
r"""
_apply_wire_bar_class.py

THE DEFECT
----------
1310-02 STUD is an 8mm dia x 65mm mild-steel ROUND BAR, welded to the hook plate.
The drawing says so explicitly, in a proper schedule table on page 4:

        ITEM  QTY  DESCRIPTION  LENGTH
          1    1    8mm DIA      65

  Tim costs it:   material £0.04 (wire)  +  Robomac £0.17
  Engine costs it: £6.69  ->  £6.96 with scrap        (~170x over)

That single line IS the entire material gap on 1310 (engine £10.60 vs Tim £6.90).

HOW IT HAPPENS — three failures stacked
---------------------------------------
1. `_is_wire_part` (document_builder.py:823) keys on the literal word "WIRE" in the
   material text, or "WIRE"+"LOOP" in the document. The stud's material is MILD STEEL and
   its description is STUD. The word "wire" appears NOWHERE. A solid round bar can never
   be recognised — the wire route was built for wire LOOPS on display products and is
   spelling-based, not shape-based.

2. `_WIRE_SIMPLE_RE` (document_builder.py:1150) requires a 3-6 DIGIT length:
        r"(\d{1,2}\.?\d*)\s*mm\s*DIA\s+(\d{3,6}\.?\d*)"
   The stud is 65. Two digits. The regex CANNOT match it.

3. With no wire match, the "8" from "8mm DIA" becomes normalized_thickness_mm = 8 — a
   DIAMETER read as a SHEET THICKNESS. With no length/width the part misses every routing
   rule in wb_populate and lands on the catch-all (rule 8: "no role, no geometry, has a
   cost -> BOM"), carrying the cost it accrued while pretending to be 8mm sheet.

WHY THE FIX INVENTS NOTHING
---------------------------
The estimators' template ALREADY prices this. Gauge lookup row 223:

        gauge 8  |  2534 m/tonne  |  =L3/I223  |  WIRE5
        L3 (Wire Cost Per Tonne) = £1,600

        £1600 / 2534 = £0.6314/m   x  0.065 m  =  £0.0410
        + 4% scrap                             =  £0.0427

Tim's manual sheet: £0.04. The WB's own formula, fed gauge 8 and length 65 straight off the
drawing, reproduces his number exactly. And the Robomac department is already in the rate
table (row 203, ROBO, £31.45/hr, 15 min setup) with nothing in the engine mapped to it.

The Wire block (rows 53-60 on the widened sheet) has NEVER been populated on any job —
wb_populate.py:480 says so outright: "no separate tube block is populated". The formulas,
the gauge table and the WIRE5 code have sat unused since day one. We are not adding a rate;
we are routing the part to the block that was built for it.

THE CHANGES
-----------
 A. _WIRE_BAR_SCHED_RE — NEW regex anchored on the drawing's TABLE STRUCTURE
        item + qty + <N>mm DIA + length
    NOT a bare "8mm DIA 65", and NOT simply widening _WIRE_SIMPLE_RE to \d{2,6}: that would
    make "8mm DIA 12 HOLES" match as a phantom 12mm wire — trading a silent under-read for
    a silent invention. Requiring the leading item/qty columns keeps it honest.

 B. _is_wire_part — add a PER-PART, GEOMETRY-ANCHORED test:
        this part's OWN pages carry a bar-schedule row, AND it has no flat pattern.
    PER-PART IS CRITICAL. doc_page_text_upper is DOCUMENT-level: a doc-level test would make
    the HOOK PLATE wire too, because the stud's schedule is in the same document. One stud
    would turn every part in the job into a bar — far worse than the bug being fixed.

 C. On recognition: set stock_form='wire', record wire_gauge_mm + wire_length_mm, and CLEAR
    normalized_thickness_mm (that 8 is a DIAMETER; leaving it is what let a bar masquerade
    as 8mm sheet).

 D. wb_populate: route stock_form == 'wire' to the WIRE BLOCK (desc/qty/gauge/length) so the
    WB's own formula prices it. Add "robomac" -> "Robomac" to OP_NAME_MAP (EXACT WB string —
    a name not in the dept table LOOKUPs to 0 and the labour is silently FREE).

 E. Fix a bug in my OWN patch from earlier today: _verify_template_matches_cellmap iterates
    ("bom", "wire", "steel", "other_sheet") but CELL_MAP names that block "tube". cm.get("wire")
    returned None and the block was silently skipped — the exact class of bug we hunted all
    day. Corrected to "tube".

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_wire_bar_class.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

DB = r"C:\ClaudeVision\src\document_builder.py"
WB = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_WIRE_BAR_SCHED_RE"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


def main():
    for p in (DB, WB):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")

    db = open(DB, "r", encoding="utf-8").read()
    wb = open(WB, "r", encoding="utf-8").read()

    if SENTINEL in db:
        sys.exit("Already applied (sentinel present).")

    print("Patching document_builder.py ...\n")

    # ---- A. bar-schedule regex + parser -------------------------------------
    db = sub(db,
             '_WIRE_SIMPLE_RE = re.compile(',
             '''# Bar / stud schedule on a DETAIL page, e.g. 1310-02:
#       ITEM  QTY  DESCRIPTION  LENGTH
#         1    1    8mm DIA      65
# Anchored on the TABLE STRUCTURE (item + qty + dia + length), NOT on a bare
# "<N>mm DIA <number>". Widening _WIRE_SIMPLE_RE's length to \\d{2,6} instead would make
# "8mm DIA 12 HOLES" match as a phantom 12mm wire — a silent invention. This does not.
_WIRE_BAR_SCHED_RE = re.compile(
    r"(?:^|\\s)(\\d{1,2})\\s+(\\d{1,3})\\s+(\\d{1,2}\\.?\\d*)\\s*mm\\s*DIA\\s+(\\d{2,5}\\.?\\d*)(?:\\s|$)",
    re.IGNORECASE,
)


def _parse_bar_schedule(page_text: str):
    """Round bar / stud rows from a part's OWN page. Returns [{gauge_mm, length_mm, qty}]."""
    out, seen = [], set()
    for m in _WIRE_BAR_SCHED_RE.finditer(page_text or ""):
        qty = int(m.group(2))
        gauge = float(m.group(3))
        length = float(m.group(4))
        if not (1.0 <= gauge <= 25.0):      # a plausible bar diameter
            continue
        if not (5.0 <= length <= 6000.0):   # a plausible cut length
            continue
        key = (gauge, length, qty)
        if key in seen:
            continue
        seen.add(key)
        out.append({"gauge_mm": gauge, "length_mm": length, "qty": qty})
    return out


_WIRE_SIMPLE_RE = re.compile(''',
             "bar-schedule regex + parser")

    # ---- B. per-part wire/bar gate ------------------------------------------
    db = sub(db,
             '''        mat_upper_joined = " ".join(str(m).upper() for m in materials)
        _is_wire_part = any(
            kw in mat_upper_joined for kw in ("WIRE", "MILD STEEL WIRE", "STEEL WIRE")
        ) or (
            "MILD STEEL WIRE" in doc_page_text_upper
            or ("WIRE" in doc_page_text_upper and "LOOP" in doc_page_text_upper)
        )''',
             '''        mat_upper_joined = " ".join(str(m).upper() for m in materials)
        _is_wire_part = any(
            kw in mat_upper_joined for kw in ("WIRE", "MILD STEEL WIRE", "STEEL WIRE")
        ) or (
            "MILD STEEL WIRE" in doc_page_text_upper
            or ("WIRE" in doc_page_text_upper and "LOOP" in doc_page_text_upper)
        )

        # ROUND BAR / STUD (added 2026-07-13). The test above keys on the literal word
        # "WIRE", so a solid bar whose drawing says "STUD" and "MILD STEEL" was never
        # recognised: 1310-02 (8mm dia x 65) was read as 8mm-THICK SHEET and priced at
        # £6.69 against Tim's £0.04.
        #
        # PER-PART, not document-level. doc_page_text_upper covers the WHOLE drawing set,
        # so testing it would make the HOOK PLATE wire as well — one stud would turn every
        # part in the job into a bar. We look ONLY at this part's own pages.
        _bar_sched = []
        if not _is_wire_part and not part.get("flat_pattern_detected"):
            _own_pages = set(part.get("pages") or [])
            if _own_pages:
                _own_text = " ".join(
                    str(_get_page_text(pg))
                    for pg in summary.get("pages", [])
                    if (pg.get("page_number") or pg.get("page")) in _own_pages
                )
                _bar_sched = _parse_bar_schedule(_own_text)
        if _bar_sched:
            _is_wire_part = True
            _b0 = _bar_sched[0]
            part["wire_gauge_mm"] = _b0["gauge_mm"]
            part["wire_length_mm"] = _b0["length_mm"]
            part["bar_schedule"] = _bar_sched
            # The "8" in "8mm DIA" is a DIAMETER, not a sheet thickness. Leaving it set is
            # exactly what let this part masquerade as 8mm sheet steel.
            part["normalized_thickness_mm"] = None
            part.setdefault("_bar_recognised", True)''',
             "per-part bar gate")

    # ---- C. stock_form + Robomac on the wire route ---------------------------
    db = sub(db,
             '''            _ops.add("wire_forming")
            _ops.add("welding")''',
             '''            _ops.add("wire_forming")
            _ops.add("welding")
            if part.get("_bar_recognised"):
                # Bars are cut on the Robomac (WB dept ROBO, £31.45/hr) — Tim charges
                # £0.17 on 1310. Not a forming op: a solid bar is cut, not looped.
                _ops.discard("wire_forming")
                _ops.add("robomac")''',
             "robomac op on recognised bars")

    db = sub(db,
             '''            part["_wire_part_override"] = True''',
             '''            part["_wire_part_override"] = True
            if part.get("_bar_recognised"):
                _me = part.setdefault("material_estimate", {})
                _me["stock_form"] = "wire"
                _me["wire_gauge_mm"] = part.get("wire_gauge_mm")
                _me["wire_length_mm"] = part.get("wire_length_mm")''',
             "stock_form=wire on recognised bars")

    # ---- D. wb_populate: op map, routing, wire block --------------------------
    print("\nPatching wb_populate.py ...\n")

    wb = sub(wb,
             '    "tube_cutting":   "Tube",',
             '    "robomac":        "Robomac",   # WB dept ROBO £31.45/hr — EXACT string or LOOKUP returns 0\n'
             '    "wire_forming":   "Robomac",\n'
             '    "tube_cutting":   "Tube",',
             "OP_NAME_MAP += Robomac")

    # E. fix my own bug: CELL_MAP calls it "tube", the check looked for "wire"
    wb = sub(wb,
             '        for key in ("bom", "wire", "steel", "other_sheet"):',
             '        for key in ("bom", "tube", "steel", "other_sheet"):  # CELL_MAP names it "tube"',
             'consistency check: "wire" -> "tube" (my bug)')

    # routing: wire parts to the wire block, BEFORE the tube->BOM rule
    wb = sub(wb,
             '''        # 4. tube — catalogue-priced section -> BOM
        elif stock_form == "tube":
            bom_parts.append(pe)''',
             '''        # 3b. wire / round bar -> Wire block (WB prices it from gauge + length)
        elif stock_form == "wire":
            wire_parts.append(pe)
        # 4. tube — catalogue-priced section -> BOM
        elif stock_form == "tube":
            bom_parts.append(pe)''',
             "routing: stock_form=wire -> wire block")

    wb = sub(wb,
             '    bom_parts, steel_parts, board_parts, weldment_parts, excluded = [], [], [], [], []',
             '    bom_parts, steel_parts, board_parts, weldment_parts, excluded = [], [], [], [], []\n'
             '    wire_parts = []',
             "wire_parts list")

    # populate the wire block — never written to before now
    wb = sub(wb,
             '''    # (Tube parts are handled in the BOM block above — catalogue-priced sections,
    #  not geometry-costed, so no separate tube block is populated.)''',
             '''    # ── Wire block: desc, qty, gauge, length ───────────────────────────────
    # Round bar / stud / wire. The WB prices it itself:
    #   gauge -> Metres Per Tonne (lookup) -> Price Per Metre = L3 / m-per-tonne
    #   cost  = (length_mm / 1000) * price_per_m * qty * (1 + scrap)
    # 8mm dia: 2534 m/t, L3 £1600/t -> £0.6314/m. 65mm -> £0.041. Tim's sheet: £0.04.
    # This block existed in the template from day one and had NEVER been populated.
    #
    # (Tube sections stay in the BOM block above — they are catalogue-priced £/EA, not
    #  costed from gauge+length like bar stock.)
    if wire_parts:
        w = cm["tube"]
        row = w["first_row"]
        for pe in wire_parts:
            if row > w["last_row"]:
                _flag(f"Wire overflow: {len(wire_parts)} wire/bar parts but only "
                      f"{w['last_row']-w['first_row']+1} rows — extras DROPPED.", flags)
                break
            me = pe.get("material_estimate") or {}
            gauge = _safe(me.get("wire_gauge_mm") or pe.get("wire_gauge_mm"))
            length = _safe(me.get("wire_length_mm") or pe.get("wire_length_mm"))
            qty = int(_safe(pe.get("quantity"), 1))
            desc = f"{pe.get('part_number') or ''}  {pe.get('description') or ''}".strip()
            if gauge is None or length is None:
                _flag(f"wire part {pe.get('part_number')} missing gauge/length "
                      f"(gauge={gauge}, length={length}) — line will be £0.", flags)
            ws.cell(row=row, column=w["col_desc"],   value=str(desc)[:120])
            ws.cell(row=row, column=w["col_qty"],    value=qty)
            ws.cell(row=row, column=w["col_gauge"],  value=gauge)
            ws.cell(row=row, column=w["col_length"], value=length)
            row += 1''',
             "populate wire block")

    # wire parts must generate labour rows (robomac / weld / handling)
    wb = sub(wb,
             '    labour_parts = list(steel_parts) + list(board_parts) + list(weldment_parts)',
             '    labour_parts = list(steel_parts) + list(board_parts) + list(weldment_parts) + list(wire_parts)',
             "wire parts get labour rows")

    wb = sub(wb,
             '''    print(f"   [wb_populate] Parts: {len(bom_parts)} BOM (incl. tube sections), "
          f"{len(steel_parts)} steel, {len(board_parts)} other-sheet, "
          f"{len(weldment_parts)} weldment (labour-only)")''',
             '''    print(f"   [wb_populate] Parts: {len(bom_parts)} BOM (incl. tube sections), "
          f"{len(wire_parts)} wire/bar, "
          f"{len(steel_parts)} steel, {len(board_parts)} other-sheet, "
          f"{len(weldment_parts)} weldment (labour-only)")''',
             "console: report wire count")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, src in ((DB, db), (WB, wb)):
        bak = f"{path}.bak_wirebar_{ts}"
        shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(src)
        print(f"\n  backup: {bak}")
        print(f"  written: {path}")

    print("""
NEXT — run 1310 (qty 50):

    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="50"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\1310 Drill Stud Holder (Rev C)" --folder-as-job

EXPECT, against Tim's manual:
    * 1310-02 STUD OUT of the BOM (no more £6.69)
    * A WIRE line: gauge 8, length 65, qty 1  ->  ~£0.04       (Tim: £0.04)
    * A Robomac labour row                     ->  ~£0.17       (Tim: £0.17)
    * Console: "1 wire/bar"
    * HOOK PLATE still in STEEL — if it moved to wire, the per-part gate leaked and this
      must be reverted immediately.

THEN regress 1282 — it has NO bars, so it must be UNCHANGED at £278.93.
Any movement means the bar gate is firing where it should not.
""")


if __name__ == "__main__":
    main()
