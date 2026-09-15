"""The table SDI has always had, and has never once had a number in it.

    "Let's look at collapsing all the s/sheets into one when we have multiple unit
     quantities. We have estimator example of how this was done."     — James Gray, 15 Sep

Howard's own 0355255 workbook is the specification, and he filled it in BY HAND: one row per
purchased material, one column per break, and the Estimate resolving the right column with
LOOKUP($D$6, ...). Change the order quantity and the sheet moves. One workbook, every
quantity — the thing we were producing four files to do.

MEASURED ON A REAL BOOK, NOT ASSUMED. 12349-02, 14 Sep:

    price cells on the break tab    0 non-empty — every row, every column
    rows available                  15 (5-19) against a BOM of 40 (Estimate 11-50)
    rows 14-19                      =_xlfn.SINGLE(Estimate!#REF!)
    Estimate J45:J50                LOOKUP into break rows 14-19, ALREADY USED by BOM rows
                                    20-25 — six lines would read six other lines' prices

So the mechanism was not broken, it was never filled in: wb_populate lists the tab under
`structural_sheets` with "NEVER overwrite these". That rule protects the estimators' layout
and it is right. What it also did was leave the table permanently empty.

Writing PRICES into a table built to hold prices is using it, not overwriting it — and only
ever into a cell that is EMPTY, because a figure an estimator typed outranks anything the
engine derived. That is the same rule the job-identity header already follows.

AND IT IS OFF UNTIL THE TEMPLATE IS REPAIRED. Filling a table that mis-routes six of its rows
would put six wrong prices on a sheet, which is worse than an empty table that puts none.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

openpyxl = pytest.importorskip("openpyxl")

import config                                                          # noqa: E402
from material_price_break import (quantity_vector, write_price_breaks)  # noqa: E402

CFG = dict(config.MATERIAL_PRICE_BREAK)


def _wb():
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    wb.create_sheet("Material Price Break")
    return wb


def _line(row, **kw):
    d = {"sheet_row": row}
    d.update(kw)
    return d


# ── the quantity row ─────────────────────────────────────────────────────────────────────

def test_the_vector_always_starts_at_one():
    """Howard's does, and for the reason somebody finds out the hard way: LOOKUP against a
    vector starting at 10 returns #N/A for an order of 1, and somebody WILL open the sheet
    at 1 to sanity-check a unit cost."""
    assert quantity_vector([10, 50, 250, 1000]) == [1, 10, 50, 250, 1000]


def test_it_is_ascending_and_deduplicated():
    """LOOKUP over an unsorted vector does not error. It returns the wrong column."""
    assert quantity_vector([250, 10, 1000, 10, 50]) == [1, 10, 50, 250, 1000]


def test_no_quantities_writes_nothing():
    assert quantity_vector([]) == []
    wb = _wb()
    out = write_price_breaks(wb, [_line(11, unit_gbp=4.5)], [], CFG)
    assert out["rows"] == 0 and out["refused"]


def test_the_quantities_are_written_on_the_estimate_not_the_structural_sheet():
    """The break tab's header reads =Estimate!F180..F190, so the numbers belong in the
    Estimate's own Qty Breaks column — which the engine already owns. Nothing of the
    estimators' layout is touched to change which quantities the sheet offers."""
    wb = _wb()
    write_price_breaks(wb, [_line(11, unit_gbp=4.5)], [10, 50, 250, 1000], CFG)
    est = wb["Estimate"]
    assert [est[f"F{180 + i}"].value for i in range(5)] == [1, 10, 50, 250, 1000]


def test_the_spare_columns_are_left_blank_not_filled_with_a_repeat():
    """THIS ASSERTED THE OPPOSITE FIRST, on the reasoning that "the vector must not go blank
    or LOOKUP returns the wrong column". That confuses a gap in the MIDDLE — which does
    break the ascending order LOOKUP needs — with cells AFTER the end, which it ignores.

    Howard's own sheet settles it: 1, 10, 50, 250, 1000, 1250, 1500 and then nothing, and it
    resolves correctly for him. Repeating the last break across six spare columns would put
    six identical headings on a tab an estimator reads."""
    wb = _wb()
    write_price_breaks(wb, [_line(11, unit_gbp=4.5)], [10, 50], CFG)
    est = wb["Estimate"]
    got = [est[f"F{180 + i}"].value for i in range(11)]
    assert got[:3] == [1, 10, 50]
    assert all(v is None for v in got[3:])


def test_the_quantities_that_are_written_still_ascend():
    """The property LOOKUP actually needs, asserted on the cells that carry a value."""
    wb = _wb()
    write_price_breaks(wb, [_line(11, unit_gbp=4.5)], [1000, 10, 250, 50], CFG)
    est = wb["Estimate"]
    got = [est[f"F{180 + i}"].value for i in range(11)]
    filled = [v for v in got if v is not None]
    assert filled == sorted(filled) == [1, 10, 50, 250, 1000]
    # and no gap between them, which is the failure that would matter
    assert got[:len(filled)] == filled


def test_more_quantities_than_columns_is_refused_not_truncated():
    """A break table quietly missing its last column is Howard's own complaint from the
    other end."""
    wb = _wb()
    out = write_price_breaks(wb, [_line(11, unit_gbp=1.0)], list(range(1, 40)), CFG)
    assert out["rows"] == 0
    assert "widen it" in " ".join(out["refused"])


# ── a price per line per break ───────────────────────────────────────────────────────────

def test_a_flat_price_is_the_same_in_every_column():
    """Tape, sheet and poly bag on Howard's sheet do not move with the order."""
    wb = _wb()
    write_price_breaks(wb, [_line(11, unit_gbp=4.50)], [10, 50, 250, 1000], CFG)
    ws = wb["Material Price Break"]
    assert [ws.cell(row=5, column=4 + i).value for i in range(5)] == [4.5] * 5


def test_a_per_order_line_amortises_and_that_is_the_point():
    """A table of five identical columns would be decoration. The stock box is why it
    earns its place."""
    wb = _wb()
    write_price_breaks(wb, [_line(12, order_gbp=1.89)], [10, 50, 250, 1000], CFG)
    ws = wb["Material Price Break"]
    got = [ws.cell(row=6, column=4 + i).value for i in range(5)]
    assert got[1] == 0.189                       # 1.89 over 10
    assert got[2] == 0.0378                      # over 50
    assert got[-1] < got[1]


def test_howards_own_box_figures_come_out():
    """1 box for 10 or 50, 3 for 250, 9 for 1000 — his email, and the row at the foot of
    his own sheet. At £1.89 a box that is 0.189 / 0.0378 / 0.02268 / 0.01701, which is
    exactly what his workbook holds."""
    wb = _wb()
    write_price_breaks(wb, [_line(13, order_gbp=1.89,
                                  units_per_order={"10": 1, "50": 1, "250": 3, "1000": 9})],
                       [10, 50, 250, 1000], CFG)
    ws = wb["Material Price Break"]
    got = [ws.cell(row=7, column=4 + i).value for i in range(1, 5)]
    assert got == [0.189, 0.0378, 0.02268, 0.01701]


def test_the_row_offset_is_a_number_not_an_assumption():
    """The template is being widened and the mapping moves with it. One number."""
    wb = _wb()
    cfg = dict(CFG, row_offset=-2)
    write_price_breaks(wb, [_line(11, unit_gbp=9.99)], [10], cfg)
    assert wb["Material Price Break"].cell(row=9, column=5).value == 9.99


def test_a_line_outside_the_bom_block_is_left_alone():
    wb = _wb()
    out = write_price_breaks(wb, [_line(999, unit_gbp=1.0)], [10, 50], CFG)
    assert out["rows"] == 0


def test_a_line_with_no_price_writes_no_cell():
    """An empty cell is the honest answer where nothing was priced. A zero is a claim."""
    wb = _wb()
    write_price_breaks(wb, [_line(11)], [10, 50], CFG)
    assert wb["Material Price Break"].cell(row=5, column=4).value is None


# ── it never displaces the estimator ─────────────────────────────────────────────────────

def test_a_figure_an_estimator_typed_is_never_overwritten():
    """The whole reason the tab was marked NEVER OVERWRITE. A typed number on this tab is
    an estimator working, and it outranks anything the engine derived."""
    wb = _wb()
    ws = wb["Material Price Break"]
    ws.cell(row=5, column=5, value=45.19)              # his supplier price, by hand
    out = write_price_breaks(wb, [_line(11, unit_gbp=48.89)], [10, 50], CFG)
    assert ws.cell(row=5, column=5).value == 45.19
    assert out["skipped_occupied"] >= 1


def test_it_refuses_rather_than_raises_on_a_workbook_that_is_not_one():
    wb = openpyxl.Workbook()                            # no break tab at all
    out = write_price_breaks(wb, [_line(11, unit_gbp=1.0)], [10], CFG)
    assert out["rows"] == 0 and out["refused"]


def test_rubbish_lines_do_not_stop_the_good_ones():
    wb = _wb()
    out = write_price_breaks(wb, [{"nonsense": True}, _line("x", unit_gbp=1),
                                  _line(11, unit_gbp=2.0)], [10], CFG)
    assert out["rows"] == 1


# ── which lines move, read off the record ────────────────────────────────────────────────

def test_a_commercial_line_is_carried_as_per_order_money(monkeypatch):
    """THE ONLY KIND THAT MOVES. A commercial line's ORDER figure is what the division has
    to be done on at each break — carrying its per-unit figure instead would give five
    identical columns and hide the one thing the table exists to show."""
    import material_price_break as mpb
    import costed_facts
    monkeypatch.setattr(costed_facts, "costed_job", lambda s: {"lines": [
        {"part_number": "PACKAGING", "sheet_row": 22, "charged_unit_gbp": 0.0},
        {"part_number": "10975", "sheet_row": 13, "charged_unit_gbp": 0.8424}]})
    out = mpb.lines_from_record({"commercial_lines": [
        {"code": "PACKAGING", "order_gbp": 1.89}]})
    got = {l["code"]: l for l in out}
    assert got["PACKAGING"]["order_gbp"] == 1.89
    assert "unit_gbp" not in got["PACKAGING"]
    assert got["10975"]["unit_gbp"] == 0.8424


def test_a_line_with_no_sheet_row_is_not_guessed_at(monkeypatch):
    """Every row comes from the workbook READ-BACK. A price cannot be placed on a row
    nobody has read, and inventing one would write a figure into another line's row."""
    import material_price_break as mpb
    import costed_facts
    monkeypatch.setattr(costed_facts, "costed_job", lambda s: {"lines": [
        {"part_number": "X", "sheet_row": None, "charged_unit_gbp": 1.0}]})
    assert mpb.lines_from_record({}) == []


def test_the_three_ways_a_line_can_move_are_written_down():
    """Measured on 10975-02 at 1 off against the same estimate at 50: every material line
    identical, every labour line moved. A future reader should not have to re-derive it."""
    src = (ROOT / "src" / "material_price_break.py").read_text(encoding="utf-8")
    assert "setup, on labour" in src
    assert "bought PER ORDER" in src
    assert "a supplier price break" in src


# ── the table is shorter than the BOM, and says so ───────────────────────────────────────

def test_a_line_below_the_tables_last_row_is_named_not_dropped():
    """NO SILENT CAP. James, on the repaired template: "break rows go to 19 from 5 —
    referencing estimate C cells to G cells from 11 to 25". Fifteen rows against forty BOM
    slots, so a material on rows 26-50 has nowhere to be priced.

    A table simply MISSING a material reads as "this one does not move with quantity",
    which is the one thing it must never say by accident — so those lines are named."""
    # A SHORT TABLE ON PURPOSE, so this tests the RULE and not whatever last_bom_row
    # happens to be today. It was 25 for the hours the repaired tab was fifteen rows long
    # and is 50 now; the next template will move it again.
    cfg = dict(CFG, last_bom_row=25)
    wb = _wb()
    out = write_price_breaks(wb, [_line(11, unit_gbp=1.0, code="TAPE"),
                                  _line(28, unit_gbp=2.0, code="POWDER")],
                             [10, 50], cfg)
    assert out["rows"] == 1
    assert any("POWDER" in s for s in out["outside_table"])
    assert not any("TAPE" in s for s in out["outside_table"])


def test_nothing_is_written_past_the_tables_last_row():
    """Numbers in cells no LOOKUP reads are invisible money, which is worse than none."""
    cfg = dict(CFG, last_bom_row=25)
    wb = _wb()
    write_price_breaks(wb, [_line(28, unit_gbp=2.0, code="POWDER")], [10, 50], cfg)
    ws = wb["Material Price Break"]
    assert ws.cell(row=22, column=4).value is None      # 28 - 6, past the table
    assert ws.cell(row=22, column=5).value is None


def test_the_last_row_itself_is_still_written():
    """Off-by-one in the other direction would drop a line the table does hold."""
    wb = _wb()
    out = write_price_breaks(wb, [_line(25, unit_gbp=3.0, code="EDGE")], [10],
                             dict(CFG, last_bom_row=25))
    assert out["rows"] == 1 and not out["outside_table"]
    assert wb["Material Price Break"].cell(row=19, column=5).value == 3.0


# ── on, against the repaired template ────────────────────────────────────────────────────

def test_it_is_on_and_reaches_the_whole_bom_block():
    """James, 15 Sep: "we now have rows 5 to 49". At an offset of -6 that covers Estimate
    rows 11 to 55, and the BOM block ends at 50 — so every slot has a break row.

    The bound is asserted against the BOM block rather than against a number typed twice:
    if the table were ever shortened again, the out-of-table report is what catches it, and
    that is tested above with a short table of its own."""
    mpb = config.MATERIAL_PRICE_BREAK
    assert mpb["enabled"] is True
    assert mpb["row_offset"] == -6
    assert mpb["last_bom_row"] == 50
    # break row of the last BOM slot must exist within the tab James built (5..49)
    assert 5 <= mpb["last_bom_row"] + mpb["row_offset"] <= 49
    assert mpb["first_bom_row"] + mpb["row_offset"] == 5


def test_the_measurements_are_recorded_not_the_impression():
    src = (ROOT / "src" / "material_price_break.py").read_text(encoding="utf-8")
    assert "0 non-empty" in src
    assert "J45:J50" in src
