#!/usr/bin/env python3
r"""
_apply_wire_schedule_per_part.py

THE BUG (document_builder.py:957)

    _ws_text = " ".join(str(_get_page_text(pg)) for pg in summary.get("pages", []))
    _wire_sched = _parse_wire_schedule(_ws_text)
    if _wire_sched:
        part["wire_schedule"] = _wire_sched        # <-- ALL THREE ROWS, ON EVERY PART

The schedule is parsed from EVERY PAGE JOINED, so all three rows get stapled to every wire
part — and to the RYOBI GREEN powder record too. No part ends up knowing its OWN length,
so none of them sets stock_form, none reaches the wire pricing route, and all three fall
through to the BOM at their LABOUR cost (£25.18 / £12.27 / £27.07 against Tim's £0.29).

THE DRAWINGS ALREADY GIVE US THE ANSWER — cleanly, one row per page:

    page 2  detail  MAIN FRAME     ITEM QTY DESCRIPTION LENGTH -> 1  1  4mm DIA  975.4
    page 3  detail  HOOK           ITEM QTY DESCRIPTION LENGTH -> 1  1  4mm DIA  233.4
    page 4  detail  BOTTOM FRAME   ITEM QTY DESCRIPTION LENGTH -> 1  1  4mm DIA  424.8

    Tim:  976 / 234 / 425 mm at 4mm gauge.   The extraction is already right to 0.6mm.

And the parts already carry pages=[2] / [3] / [4].

THE FIX: read the schedule from THE PART'S OWN PAGES ONLY — the identical per-part gate
that fixed the 1310 stud this morning. Then hand off to the bar chain that already exists:
_bar_recognised -> workbook_bar_formula -> Wire block -> Robomac -> sheet-ops dropped.

Nothing new is invented. Everything downstream was built and verified today.

EXPECTED (wire at the template's £1,600/tonne; 4mm dia -> 10,138 m/tonne, and Tim's own
sheet says 10,140, so the derivation agrees with his table):

    7670-01-001  975.4mm x1   ~£0.16      Tim £0.15
    7670-01-002  233.4mm x2   ~£0.08      Tim £0.07
    7670-01-003  424.8mm x1   ~£0.07      Tim £0.07
                              ------
                              ~£0.31      Tim £0.29

The small excess is the WIRE RATE, not the maths: Tim's sheet is dated 05/01/2026 and uses
£1,500/tonne; the template says £1,600. That looks like a genuine price rise rather than a
bug, so it is NOT changed here — flag it for Tim rather than quietly matching his old number.

A SECOND BUG, FOUND IN THE SAME PAGE TEXT — and it is an apology to Design:

    drawing says:   MATERIAL: MILD STEEL WIRE
    engine stores:  normalized_material = MILD_STEEL      <-- "WIRE" discarded

The material FORM is on the drawing. Design already do the thing we were about to ask them
for. The normaliser is throwing it away. Not fixed here (one change at a time), but it goes
straight to the top of the list — it would make the whole bar/wire recognition trivial
instead of regex-driven.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_wire_schedule_per_part.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\document_builder.py"
SENTINEL = "_own_wire_pages"

OLD = '''            _ws_text = " ".join(str(_get_page_text(pg)) for pg in summary.get("pages", []))
            _wire_sched = _parse_wire_schedule(_ws_text)
            if _wire_sched:
                part["wire_schedule"] = _wire_sched
                part["wire_total_length_mm"] = round(
                    sum(r["total_length_mm"] for r in _wire_sched), 2
                )'''

NEW = '''            # ── Wire schedule: read the part's OWN pages, not the whole document ──
            # Was: " ".join(every page) -> all three schedule rows stapled onto EVERY wire
            # part AND onto the bought-in powder record. No part knew its own length, so
            # none set stock_form, none reached the wire pricing route, and all three fell
            # into the BOM at their LABOUR cost (£25.18/£12.27/£27.07 vs Tim's £0.29 total).
            #
            # The drawings make this easy — one schedule row per detail page:
            #     page 2  MAIN FRAME     ITEM QTY DESCRIPTION LENGTH -> 1 1 4mm DIA 975.4
            #     page 3  HOOK                                       -> 1 1 4mm DIA 233.4
            #     page 4  BOTTOM FRAME                               -> 1 1 4mm DIA 424.8
            # (Tim: 976 / 234 / 425mm at 4mm. The extraction was already right to 0.6mm —
            #  it was only ever attached to the wrong record.)
            #
            # Same per-part gate that fixed the 1310 stud. Then hand off to the bar chain
            # that already exists: _bar_recognised -> workbook_bar_formula -> Wire block ->
            # Robomac -> sheet-ops dropped.
            _own_wire_pages = set(part.get("pages") or [])
            if _own_wire_pages:
                _ws_text = " ".join(
                    str(_get_page_text(pg))
                    for pg in summary.get("pages", [])
                    if (pg.get("page_number") or pg.get("page")) in _own_wire_pages
                )
            else:
                # No page ownership (bought-in stubs, doc-level records): read NOTHING.
                # A record with no pages has no wire schedule of its own — that is exactly
                # how the powder line ended up holding all three rows.
                _ws_text = ""
            _wire_sched = _parse_wire_schedule(_ws_text) if _ws_text else []
            if _wire_sched:
                part["wire_schedule"] = _wire_sched
                part["wire_total_length_mm"] = round(
                    sum(r["total_length_mm"] for r in _wire_sched), 2
                )
                # One schedule row on the part's own page = this part IS that wire form.
                # Feed the bar chain built for the 1310 stud; everything downstream is
                # already in place and verified.
                if len(_wire_sched) == 1:
                    _r0 = _wire_sched[0]
                    _g = _r0.get("gauge_mm")
                    _l = _r0.get("length_mm") or _r0.get("total_length_mm")
                    if _g and _l:
                        part["_bar_recognised"] = True
                        part["wire_gauge_mm"] = float(_g)
                        part["wire_length_mm"] = float(_l)
                        # A DIAMETER is not a sheet THICKNESS. 4mm dia was being read as
                        # 4mm plate — the same misread that costed the 1310 stud as sheet.
                        part["normalized_thickness_mm"] = None
                        _me = part.setdefault("material_estimate", {})
                        _me["stock_form"] = "wire"
                        _me["wire_gauge_mm"] = float(_g)
                        _me["wire_length_mm"] = float(_l)
                else:
                    # More than one row on a single part's pages: we do NOT pick one and
                    # hope. Silently binding the wrong length is worse than an admitted gap.
                    part.setdefault("review_flags", []).append(
                        f"{part.get('part_number')}: {len(_wire_sched)} wire-schedule rows on "
                        f"this part's own page(s) — cannot tell which belongs to the part. "
                        f"NOT costed as wire. Estimator to confirm."
                    )'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")
    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match for the wire-schedule block, found {n}. "
                 f"Nothing written.")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_wiresched_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  wire schedule now bound per-part from the part's own pages")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 7670 (qty 50):

    $env:PYTHONIOENCODING="utf-8"
    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="50"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\7670-01-AEG ORANGE A4 LEAFLET HOLDER" --folder-as-job

EXPECT:
  * console: "3 wire/bar"
  * the three parts OUT of the BOM
  * WIRE block:  gauge 4, lengths 975.4 / 233.4 / 424.8  -> ~£0.31   (Tim £0.29)
  * Robomac rows appear                                              (Tim £1.03 across 3)
  * NO laser / fold on any of them (spurious-op gate)
  * the RYOBI GREEN powder line no longer carries a wire schedule

STILL WRONG AFTERWARDS, AND WORTH SEEING CLEARLY:
  * £17.86/part of POWDER-COATING LABOUR x3 = £53.58 against Tim's £1.92 TOTAL. This is
    now the single biggest error in the job by a wide margin, and nothing above touches it.
  * Robomac grouping: Tim writes ONE ROW PER WIRE FORM (100 / 450 / 300 per hour — each
    form is a different bend program). My grouping patch collapses Robomac to one row per
    job. It will UNDER-charge here. Must be fixed.
  * The three parts are RAW and that is CORRECT — the ASSEMBLY is coated. The engine has no
    concept of an assembly-level finish, so Tim's £0.40 powder + £1.92 P.Coat go missing.

THEN regress 1310 (qty 50) — its stud is a BAR, recognised by a different regex on its own
page. It must still price at £0.04. If it moves, this patch has reached further than intended.
""")


if __name__ == "__main__":
    main()
