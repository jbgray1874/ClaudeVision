r"""Two faults the previous round's tests could not have caught, because they proved names.

James, reviewing 57db153:

  1. "brush_before_plate maps to Manual labour (Metal), while plater_pack and
     plater_final_pack both map to Assemble/pack (Metal). The grouping logic then keys
     one-row-per-job work solely by that displayed title... So the two pack stages can
     still collapse into one row before the stated-time logic runs. The new tests prove
     names, rates and aliases - not an actual populated workbook containing separate 40-,
     4- and 8-minute rows."

  2. "#REF! is suppressed, not mapped correctly... It risks converting an explicitly
     unresolved plating cost into a blank/zero contribution. The workbook should instead
     write an explicit 'awaiting current quote' line and a valid price-break mapping or
     deliberately blank price cells - not retain a broken template formula until the final
     scrub."

Both are right, and the second is the sharper criticism: the hygiene scrub exists to catch
what nobody can enumerate, and leaning on it HERE hid a broken reference instead of
deciding what the line should say.

So these tests are about BEHAVIOUR rather than vocabulary: the grouping key on real inputs,
and the price cell on a real worksheet.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config          # noqa: E402
import wb_populate     # noqa: E402


# ── 1 · a stated operation keeps its own row ─────────────────────────────────────────

# The EMITTER'S OWN FUNCTION, not a copy of its branch. The first version of this file
# rebuilt the rule here and asserted against that, which passes whether or not the engine
# agrees with it -- two copies of one fact, the same fault the register keeps finding.
_PER_PART = {"Robomac"}
_ONE_ROW = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)", "Packing Joinery",
            "Weld (CO2)", "Spotweld", "Dress Welds", "P.Coat"}


def _key(op: str, wb_op: str, part: str = "7332-01-101",
         material: str = "MILD STEEL", thickness: float = 1.0):
    return wb_populate.labour_group_key(op, wb_op, part, material, thickness,
                                        per_part_ops=_PER_PART,
                                        one_row_per_job=_ONE_ROW)


def test_the_two_pack_stages_do_not_share_a_key():
    """Both are "Assemble/pack (Metal)", so the old key collapsed them before the
    stated-time lookup ever ran."""
    out = _key("plater_pack", "Assemble/pack (Metal)")
    back = _key("plater_final_pack", "Assemble/pack (Metal)")
    assert out != back, "the pack out and the pack back still merge into one row"


def test_brushing_does_not_share_a_key_with_other_manual_metal_work():
    """Same department, same material, same gauge — which is the whole old key."""
    brush = _key("brush_before_plate", "Manual labour (Metal)")
    deburr = _key("deburr", "Manual labour (Metal)")
    bench = _key("bench_work", "Manual labour (Metal)")
    assert brush != deburr and brush != bench


def test_brushing_keeps_one_row_across_parts_and_gauges():
    """Its own row for the job, not one per gauge: a stated per-unit time is not a
    property of the material it happens to be applied to."""
    assert _key("brush_before_plate", "Manual labour (Metal)",
                part="A", material="MILD STEEL", thickness=1.0) == \
           _key("brush_before_plate", "Manual labour (Metal)",
                part="B", material="STAINLESS", thickness=2.0)


def test_the_old_key_really_did_merge_them():
    """The control, driven through the SAME function: an operation that is not on the
    stated list still keys by department alone, so two of them share a row. That is the
    behaviour the pack stages used to get."""
    assert _key("assembly", "Assemble/pack (Metal)") == \
        _key("handling", "Assemble/pack (Metal)"), (
        "unstated work in one department still shares a row, which is correct — and is "
        "exactly what was happening to the two stated pack stages")


def test_every_stated_operation_still_shows_its_department_title():
    """The row must keep billing at the bench's own rate and reading as the bench's own
    work — the fix is to the KEY, not to what an estimator sees."""
    for op in config.STATED_TIME_OPERATIONS:
        title = wb_populate.OP_NAME_MAP.get(op)
        assert title, op
        assert _key(op, title)[0] == title


def test_the_list_of_stated_operations_lives_in_config():
    """"Can we put these into a central area that is easy to identify and change if
    needed" — Howard Thurley. A rule added to config without a row here would merge
    silently, which is the fault this exists to stop."""
    assert config.STATED_TIME_OPERATIONS
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert 'getattr(config, "STATED_TIME_OPERATIONS", ())' in src, (
        "wb_populate keeps its own copy of the list, which is two places to edit")


def test_the_stated_ops_are_the_ones_with_stated_minutes():
    """The list is not 'important operations'. Each entry must have a figure a person gave
    us, in config, or it does not belong."""
    assert set(config.STATED_TIME_OPERATIONS) == {
        "brush_before_plate", "plater_pack", "plater_final_pack"}
    assert config.BRUSH_BEFORE_PLATE["minutes_per_unit"] == 40.0
    assert config.PLATING_LOGISTICS["pack_for_plater_min"] == 4.0
    assert config.PLATING_LOGISTICS["final_pack_min"] == 8.0


# ── 2 · the price cell, on a real worksheet ──────────────────────────────────────────

_TEMPLATE_BROKEN = ("=LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,"
                    "'Material Price Break'!#REF!)")
_TEMPLATE_OK = ("=LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,"
                "'Material Price Break'!D14:N14)")
_OURS = ("=IF('Material Price Break'!D14=\"\",0,"
         "LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,'Material Price Break'!D14:N14))")


def test_a_formula_this_engine_wrote_is_told_apart_from_the_templates():
    """By SHAPE, because remembering is what failed — a row the loop never reached keeps
    the template's formula and no record says so."""
    assert wb_populate._ours_by_shape(_OURS)
    assert not wb_populate._ours_by_shape(_TEMPLATE_BROKEN)
    assert not wb_populate._ours_by_shape(_TEMPLATE_OK), (
        "a bare LOOKUP in a price cell is the template still speaking, whether or not it "
        "says #REF! today")
    assert not wb_populate._ours_by_shape(None)
    assert not wb_populate._ours_by_shape(12.40)


def test_a_working_template_formula_is_caught_too_not_only_a_broken_one():
    """The complaint was about #REF!, but a bare LOOKUP that happens to evaluate is the
    same fault with a luckier reference — it prices the line off a row nobody assigned it."""
    assert not wb_populate._ours_by_shape(_TEMPLATE_OK)


def test_an_unresolved_line_is_never_left_as_a_silent_zero():
    """James: blanking it in the final scrub "risks converting an explicitly unresolved
    plating cost into a blank/zero contribution". A blank is only honest if the line SAYS
    it is waiting."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    start = src.index("_stranded: List[str] = []")
    block = src[start:start + 2600]
    assert 'AWAITING A CURRENT PRICE' in block
    assert "_mark_input_cell(ws, _r, b[\"col_price\"])" in block, (
        "the cell must be coloured as something a person has to fill in — a bare blank is "
        "discoverable rather than visible")
    assert "_clear_or_set(ws, _r, b[\"col_price\"], None)" in block


def test_the_decision_happens_at_the_block_not_in_the_final_scrub():
    """The hygiene pass catches what nobody could enumerate. Leaning on it for a line whose
    intent IS known hides the fault instead of deciding the behaviour."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert src.index("_stranded: List[str] = []") < src.index("from workbook_hygiene import"), (
        "the BOM sweep must run long before the final scrub, or the scrub gets there first")


def test_the_scrub_still_backs_it_up_everywhere_else():
    """Belt and braces, and they are not the same garment: the sweep decides the BOM's own
    price cells, the scrub is the last line of defence for every other cell on every sheet."""
    from workbook_hygiene import is_broken_formula, scrub_workbook
    openpyxl = pytest.importorskip("openpyxl")
    assert is_broken_formula(_TEMPLATE_BROKEN)
    wb = openpyxl.Workbook()
    wb.active["Z9"] = _TEMPLATE_BROKEN
    _changed, _where, broken = scrub_workbook(wb)
    assert broken and wb.active["Z9"].value is None


# ── the sweep itself, on a real worksheet ────────────────────────────────────────────

def _sweep(ws, first_row: int, last_row: int, used_to: int, cols: dict):
    """The BOM price sweep, driven the way wb_populate drives it.

    The loop body is reproduced here against a real openpyxl sheet because the sweep lives
    inside populate_workbook, which needs the estimators' template off a UNC path this
    container has never seen. What is NOT reproduced is the DECISION -- `_ours_by_shape`
    is the engine's own, and it is the thing that was wrong.
    """
    stranded = []
    for r in range(first_row, min(used_to, last_row + 1)):
        if not (ws.cell(row=r, column=cols["col_code"]).value
                or ws.cell(row=r, column=cols["col_desc"]).value):
            continue
        pv = ws.cell(row=r, column=cols["col_price"]).value
        if pv is None or not isinstance(pv, str) or not pv.startswith("="):
            continue
        if wb_populate._ours_by_shape(pv):
            continue
        stranded.append(r)
        ws.cell(row=r, column=cols["col_price"]).value = None
        d = ws.cell(row=r, column=cols["col_desc"]).value
        if "AWAITING A CURRENT PRICE" not in str(d or ""):
            ws.cell(row=r, column=cols["col_desc"],
                    value=f"{str(d or '')[:150]}  —  AWAITING A CURRENT PRICE"[:200])
    return stranded


def _bom_sheet():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    cols = {"col_desc": 3, "col_code": 8, "col_price": 10}
    return ws, cols


def test_the_plating_line_comes_out_blank_and_says_it_is_waiting():
    """J20 on the delivered book: a plating stub the engine deliberately left unpriced,
    carrying the blank template's own broken LOOKUP, with M20 inheriting the error."""
    ws, cols = _bom_sheet()
    ws.cell(20, cols["col_desc"], "7332-01-101-PLATE  plating")
    ws.cell(20, cols["col_code"], "7332-01-101-PLATE")
    ws.cell(20, cols["col_price"], _TEMPLATE_BROKEN)

    stranded = _sweep(ws, 11, 50, 25, cols)

    assert stranded == [20]
    assert ws.cell(20, cols["col_price"]).value is None, "the #REF! is still in the book"
    assert "AWAITING A CURRENT PRICE" in ws.cell(20, cols["col_desc"]).value, (
        "a blank price with nothing said is a silent zero — exactly what must not happen "
        "to an explicitly unresolved plating cost")
    assert "7332-01-101-PLATE" in ws.cell(20, cols["col_desc"]).value, (
        "the line keeps its own description; the note is added, not substituted")


def test_a_line_the_engine_priced_off_the_break_table_is_left_alone():
    """The formula this run wrote is how a per-order line amortises through D6. Clearing it
    would freeze packaging at one quantity, which is the fault the break mechanism exists
    to prevent."""
    ws, cols = _bom_sheet()
    ws.cell(21, cols["col_desc"], "PACKAGING")
    ws.cell(21, cols["col_code"], "PACKAGING")
    ws.cell(21, cols["col_price"], _OURS)

    assert _sweep(ws, 11, 50, 25, cols) == []
    assert ws.cell(21, cols["col_price"]).value == _OURS
    assert "AWAITING" not in str(ws.cell(21, cols["col_desc"]).value)


def test_a_priced_line_and_an_already_blank_line_are_both_decisions():
    ws, cols = _bom_sheet()
    ws.cell(22, cols["col_desc"], "FIXING535")
    ws.cell(22, cols["col_code"], "FIXING535")
    ws.cell(22, cols["col_price"], 0.05)
    ws.cell(23, cols["col_desc"], "DBR60  —  AWAITING A CURRENT PRICE")
    ws.cell(23, cols["col_code"], "DBR60")

    assert _sweep(ws, 11, 50, 25, cols) == []
    assert ws.cell(22, cols["col_price"]).value == 0.05
    assert ws.cell(23, cols["col_price"]).value is None
    assert ws.cell(23, cols["col_desc"]).value.count("AWAITING") == 1, (
        "the note must not be appended twice on a re-run")


def test_a_template_row_the_engine_never_claimed_is_not_touched():
    """The sweep is about rows the engine put a line on. An empty template row below the
    block is the template's business, and rewriting it would be this engine editing a sheet
    it does not own."""
    ws, cols = _bom_sheet()
    ws.cell(30, cols["col_price"], _TEMPLATE_BROKEN)      # no code, no description
    assert _sweep(ws, 11, 50, 40, cols) == []
    assert ws.cell(30, cols["col_price"]).value == _TEMPLATE_BROKEN, (
        "left for the final hygiene scrub, which is what that pass is for")
