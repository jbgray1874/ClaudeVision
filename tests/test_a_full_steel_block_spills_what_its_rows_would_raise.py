"""12645 19:17 book (D-318). Thirty-six Sheet Steel parts for a nineteen-row block: seventeen
spilled to the Bill of Materials as "Sheet Steel block full — PROVISIONAL".

Two of them are the 3,020 mm cover plates (12645-01-32M x1, -33M x3), longer than every stocked
sheet. D-314 makes a block row raise that as a manufacturing decision and charge no steel;
spilled, they skipped the row, so nothing was raised and each carried £45.92 — one 2500 x 1250
sheet that cannot hold them (£191.03 with the line's scrap). And not one of the seventeen was
counted: the banner read "5 to settle: 4 market figures to replace + 1 quantity check" over
£746.50 of steel no block had nested, £28.71 of it a second 4% on figures that already
carried scrap.
"""
from __future__ import annotations

import os
import sys

import openpyxl

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts as cf  # noqa: E402
import wb_populate as wp  # noqa: E402

_S = dict(wp.CELL_MAP["steel"], first_row=93, last_row=111)


def _sheet():
    ws = openpyxl.Workbook().active
    ws.title = "Estimate"
    ws.cell(93, _S["col_sheet_l"], 2500)
    ws.cell(93, _S["col_sheet_w"], 1250)
    return ws


def _steel(pn, length, width, gauge=2.0, qty=1, cost=45.92):
    return {"part_number": pn, "description": "PANEL", "quantity": qty,
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": gauge,
            "normalized_geometry": {"blank_length_mm": length, "blank_width_mm": width},
            "material_estimate": {"stock_form": "sheet", "cost_per_part_gbp": cost,
                                  "cost_method": "workbook_sheet_steel_formula",
                                  "blank_length_mm": length, "blank_width_mm": width}}


def test_a_spilled_flat_no_listed_sheet_holds_raises_what_its_row_would():
    ws, flags = _sheet(), []
    giant = _steel("X-01M", 4500.0, 727.39)
    line = wp.spill_from_full_block(ws, "Sheet Steel", "steel", _S, giant, flags)
    row_part, row_flags = _steel("X-01M", 4500.0, 727.39), []
    wp.raise_unnestable_steel(row_part, 4500.0, 727.39,
                              wp.steel_sheet_for_row(4500.0, 727.39, "MILD_STEEL",
                                                     (2500, 1250))[1], row_flags)
    assert giant["route_gap"] == row_part["route_gap"]
    assert "every stocked sheet" in giant["route_gap"]["issue"]
    assert wp._bom_line_price(line) is None
    assert "NOT PRICED" in line["description"]
    assert giant["block_overflow"]["basis"] == "no_stocked_sheet"


def test_a_spilled_oversize_flat_is_priced_provisionally_and_its_route_asked():
    """12645-01-32M, 3020.02 x 727.39 (D-332): priced — the engine now costs it on the
    listed 4000 x 1830 sheet — counted as provisional, and the make-or-buy route raised the
    same way the block row raises it."""
    ws, flags = _sheet(), []
    cover = _steel("12645-01-32M", 3020.02, 727.39, cost=53.79)
    line = wp.spill_from_full_block(ws, "Sheet Steel", "steel", _S, cover, flags)
    row_part, row_flags = _steel("12645-01-32M", 3020.02, 727.39), []
    wp.raise_oversize_route(row_part, 3020.02, 727.39,
                            wp.steel_sheet_for_row(3020.02, 727.39, "MILD_STEEL",
                                                   (2500, 1250))[1], row_flags)
    assert cover["route_gap"] == row_part["route_gap"]
    assert "4000 x 1830" in cover["route_gap"]["issue"]
    assert "not both" in cover["route_gap"]["action"]
    assert line["unit_cost_gbp"] == 53.79
    assert "PROVISIONAL: oversize 4000 x 1830" in line["description"]
    assert cover["block_overflow"]["basis"] == "net_part_provisional"


def test_a_spilled_flat_that_fits_keeps_its_figure_and_is_marked_provisional():
    ws, flags = _sheet(), []
    panel = _steel("12645-01-23M", 2226.68, 1051.68)
    line = wp.spill_from_full_block(ws, "Sheet Steel", "steel", _S, panel, flags)
    assert "route_gap" not in panel
    assert line["unit_cost_gbp"] == 45.92
    assert panel["block_overflow"] == {"block": "Sheet Steel", "basis": "net_part_provisional"}
    assert len(line["description"]) <= 120 + len("PANEL — ")    # fits the cell it is cut to


def _summary(parts):
    return {"estimate_summary": {"part_estimates": parts}, "invariants": {"violations": []}}


def test_every_provisional_spilled_line_is_counted_in_the_one_tally():
    parts = [_steel("12645-01-23M", 2226.68, 1051.68), _steel("12645-01-26M", 2935.01, 1126.68)]
    for p in parts:
        p["block_overflow"] = {"block": "Sheet Steel", "basis": "net_part_provisional"}
    s = cf.outstanding_summary(_summary(parts))
    assert "2 provisional lines to nest by hand" in s["phrase"]
    assert s["blocking"] == 2 and s["other"] == 0
    rel = cf.costed_job(_summary(parts))["release"]
    assert rel["draft"] and rel["status"] == "provisional" and rel["outstanding"] == 2


def test_a_line_nested_by_the_blocks_own_formulas_is_not_provisional():
    part = _steel("12633-03-01P", 450, 45)
    part["block_overflow"] = {"block": "Other Sheet Material", "basis": "nested_by_block_formulas"}
    assert "provisional" not in cf.outstanding_summary(_summary([part]))["phrase"]


def test_a_spilled_figure_that_already_carries_scrap_is_not_scrapped_again():
    """26M: engine £45.92 x 4 = £183.68 already includes 4%; the line charged £191.03."""
    ws, flags = _sheet(), []
    line = wp.spill_from_full_block(ws, "Sheet Steel", "steel", _S,
                                    _steel("12645-01-26M", 2935.01, 1126.68, qty=4), flags)
    assert wp.waste_already_in_price(line)
    # a panel inside the block still keeps the sheet's 4%: the rule is the spill's, not steel's
    assert not wp.waste_already_in_price(_steel("12645-01-01M", 2912.54, 1087.54, 4.0, 3))


# ── the CALL SITES, not merely the definitions ───────────────────────────────────────────
# The template is not in the repo, so populate_workbook cannot run here end to end. These
# pin that the writer actually calls the helpers the tests above exercise (house style:
# test_estimating_rules, "The CALL SITE, not merely the definition").

def _writer_source():
    import inspect
    import wb_populate
    return inspect.getsource(wb_populate.populate_workbook)


def test_the_spill_loop_asks_the_fit_question():
    src = _writer_source()
    call = src.index("spill_from_full_block(ws, _blk_name, _blk_key, _cap_map, _sp, flags)")
    # inside the loop that then truncates the block — before the steel writer sees it
    assert "del _blk_list[_cap:]" in src[call:call + 3000]


def test_the_bom_writer_and_the_steel_writer_use_the_shared_rules():
    src = _writer_source()
    assert "_waste_already_in = waste_already_in_price(pe)" in src
    assert "raise_unnestable_steel(pe, length, width, _why, flags)" in src


def test_a_withheld_spilled_line_keeps_its_reason_on_the_sheet():
    """The BOM writer's unpriced branch rewrote the description as "<desc[:70]> — enter the
    per-unit figure", which dropped "no stocked sheet holds it": 12645's 3,020 mm covers
    would have read as an ordinary missing price rather than a make decision."""
    src = _writer_source()
    assert '_block_overflow_basis") == "no_stocked_sheet"' in src
    assert "NOT PRICED — {pe['route_gap']['issue']}" in src
