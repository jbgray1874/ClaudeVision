"""The M&S plywood bin, costed from its enquiry brief. Book of 30 Sep, 14:12.

The brief worked: "350off … Plywood construction with print … 600 x 600 x 1200mm bump bin
with lid with 1800mm back panel" gave ten parts, all plywood, sized from the brief. The book
it produced carried four engine faults, all fixed here:

D-364
* THE CUSTOMER CELL SHOWED THE DRAWING NUMBER. --customer "M&S" reached the deliverables and
  not the workbook, which guessed the customer from a local folder's path. The same name picks
  the customer's commercial terms, so the book also went out at the template's rebate 0 and
  /0.93 instead of M&S's 1.8% and /0.92, about 2.9% light.
* THE BASE WENT ON THE WRONG SHEET. The sheet was chosen by count across sheet sizes, so
  564 x 564 took 3050 x 1525 (10 a sheet, 68% used) over 2440 x 1220 (8 a sheet, 86% used).
* THE BIN WAS FITTED IN 45 SECONDS. The house bench allowance, named min_per_part, was
  charged once for the whole assembly (2 min), and the floor guard then replaced it with the
  79/hr department median.

D-365
* THE PRINT WAS NOT COSTED. Five panels came back as "green printed plywood" and no graphic
  line, so the board was priced and the print the brief asked for was free.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan                                                      # noqa: E402
import config                                                            # noqa: E402
import estimator                                                         # noqa: E402
import wb_populate                                                       # noqa: E402


# ── D-364: the customer the run was given ───────────────────────────────────────────────

def test_the_customer_given_to_the_run_reaches_the_workbook():
    src = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
    set_at = src.index('summary["customer"] = str(args.customer).strip()')
    populate_at = src.index("xlsx_path = populate_workbook(summary, str(scan_label))")
    assert set_at < populate_at, "the customer has to be on the summary before the book"


def test_the_workbook_reads_the_summarys_customer_first():
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert '_customer_name = (summary.get("customer") or summary.get("client")' in src


def test_the_name_brings_the_customers_terms():
    """Why the cell matters for money and not only for the heading."""
    terms = config.customer_commercial_terms("M&S")
    assert terms["rebate_fraction"] == 0.018 and terms["absorption_divisor"] == 0.92
    # What the 14:12 book was headed with: the folder's name. It carries no terms, so the
    # sheet took the template's rebate 0 and /0.93.
    assert config.customer_commercial_terms("bdab4adf-3340-40M&S") is None


# ── D-364: the sheet is chosen by yield ─────────────────────────────────────────────────

def test_the_plywood_base_goes_on_the_sheet_it_uses_best():
    se = estimator.select_sheet_size("PLYWOOD", 564.0, 564.0)
    assert se["candidate_sheet_size_mm"] == [2440, 1220]
    assert se["parts_per_sheet"] == 8 and se["utilisation_pct"] > 85


def test_a_part_the_bigger_sheet_really_suits_still_takes_it():
    """Yield, not "the smaller sheet": the 600 x 600 top uses 62% of 3050 x 1525 and 36% of
    2440 x 1220."""
    se = estimator.select_sheet_size("PLYWOOD", 600.0, 600.0)
    assert se["candidate_sheet_size_mm"] == [3050, 1525] and se["parts_per_sheet"] == 8


def test_an_equal_count_takes_the_sheet_with_less_waste():
    """The old rule kept the FIRST sheet on a tied count: an MFC panel two to a sheet went
    on 2800 x 2070 (37% used) over 3080 x 1220 (57% used)."""
    se = estimator.select_sheet_size("MFC", 1434.0, 748.0)
    assert se["candidate_sheet_size_mm"] == [3080, 1220]


def test_a_near_tie_does_not_move_a_job_to_another_sheet():
    """53.2% against 53.0% buys nothing; the 11650 door stays on the sheet it was charged on."""
    assert config.SHEET_CHOICE_YIELD_TIE_PCT == 1.0
    se = estimator.select_sheet_size("ACRYLIC", 1202.0, 689.0)
    assert se["candidate_sheet_size_mm"] == [3050, 2050] and se["parts_per_sheet"] == 4


def test_steel_still_takes_the_smallest_sheet_it_nests_on():
    se = estimator.select_sheet_size("MILD STEEL", 500.0, 290.0)
    sizes = sorted(estimator._costed_facts.stocked_sheet_sizes("MILD STEEL"),
                   key=lambda s: s[0] * s[1])
    assert se["candidate_sheet_size_mm"] == list(sizes[0])


# ── D-364: the bench allowance is per part fitted ───────────────────────────────────────

def _plywood_bin(children: int = 8) -> dict:
    return {"part_number": "BDAB4ADF-3340-40M-S-CPT00", "description": "BUMP BIN WITH LID",
            "normalized_material": "PLYWOOD", "quantity": 1, "is_assembly_parent": True,
            "assembly_children": [f"BDAB4ADF-3340-40M-S-CPT{n:02d}"
                                  for n in range(1, children + 1)]}


def test_a_plywood_bin_is_fitted_for_each_part_it_is_made_of():
    part = _plywood_bin(8)
    est = estimator.estimate_part(part, job_quantity=350)
    per_part = float(config.LABOUR_RULES["bench_work"]["min_per_part"])
    mins = (est.get("process_estimate") or {}).get("run_times_min_per_unit", {}).get("bench_work")
    assert mins == per_part * 8 == 16.0, mins
    flags = " ".join(part.get("review_flags") or [])
    assert f"{per_part:g} min for each of 8 part(s) fitted" in flags
    assert part.get("bench_work_applied") is True


def test_an_assembly_with_no_listed_children_still_gets_one_allowance():
    part = _plywood_bin(0)
    part["canonical_kind"] = "assembly"
    est = estimator.estimate_part(part, job_quantity=350)
    mins = (est.get("process_estimate") or {}).get("run_times_min_per_unit", {}).get("bench_work")
    assert mins == float(config.LABOUR_RULES["bench_work"]["min_per_part"])


def test_the_bench_rule_is_a_stated_time_the_floor_guard_leaves_alone():
    """The floor guard is there to catch garbage derivations. The rule's own minutes are not
    one. Without the claim, 16 minutes a bin (3.75/hr) is replaced by 79/hr again."""
    markers = {m: set(ops) for m, ops, _ in wb_populate._STATED_SHOP_TIME_MARKERS}
    assert markers.get("bench_work_applied") == {"bench_work"}
    stated = {"CPT00": "the bench-fitting rule"}
    group = {"parts": ["CPT00"], "engine_ops": ["bench_work"]}
    assert wb_populate._group_carries_a_stated_shop_time(
        group, stated, {"CPT00": {"bench_work"}})


def test_the_bench_claim_vouches_for_the_bench_and_nothing_else():
    """The unit's packing and the panels' saw and edge rows keep their guards."""
    stated = {"CPT00": "the bench-fitting rule"}
    for op in ("packing_joinery", "assembly", "saw", "edge_banding", "manual_labour_metal"):
        group = {"parts": ["CPT00"], "engine_ops": [op]}
        assert not wb_populate._group_carries_a_stated_shop_time(
            group, stated, {"CPT00": {"bench_work"}}), op


# ── D-365: print is its own line ────────────────────────────────────────────────────────

def _panel(name, material, length=1200, width=564, quantity=1):
    return {"name": name, "kind": "fabricated", "sighted_material": material,
            "material_guess": "PLYWOOD",
            "assumed_blank_mm": {"length": length, "width": width, "thickness": 18},
            "quantity": quantity, "quantity_basis": "brief", "operations": ["saw"],
            "seen": "render", "why_size": "the brief"}


def _answer(*parts):
    return {"parts": list(parts)}


def test_a_panel_described_as_printed_gets_a_print_line_of_its_own():
    answer = concept_scan._with_print_lines(_answer(
        _panel("FRONT PANEL", "green printed plywood"),
        _panel("SIDE PANEL", "green printed plywood", 1200, 582, quantity=2),
        _panel("BASE", "plywood", 564, 564)))
    prints = [p for p in answer["parts"] if p["kind"] == "graphic"]
    assert [p["name"] for p in prints] == ["PRINT — FRONT PANEL", "PRINT — SIDE PANEL"]
    front, side = prints
    assert front["assumed_blank_mm"]["length"] == 1200
    assert front["assumed_blank_mm"]["width"] == 564
    assert side["quantity"] == 2, "one print per printed panel, as many as there are panels"
    assert front["_panel_said"] == "green printed plywood", "what the model saw, not the code"


def test_a_model_that_listed_the_print_is_never_charged_twice():
    answer = _answer(_panel("FRONT PANEL", "green printed plywood"),
                     {"name": "GRAPHIC SET", "kind": "graphic",
                      "sighted_material": "printed vinyl", "material_guess": "BOUGHT_IN",
                      "assumed_blank_mm": {"length": 1200, "width": 564, "thickness": 0},
                      "quantity": 1})
    assert concept_scan._with_print_lines(answer) is answer


def test_an_unprinted_board_and_a_printed_purchase_mint_nothing():
    answer = _answer(_panel("BASE", "plywood"),
                     {"name": "CASTOR", "kind": "bought_in",
                      "sighted_material": "printed-logo castor", "material_guess": "BOUGHT_IN",
                      "assumed_blank_mm": {}, "quantity": 4})
    assert concept_scan._with_print_lines(answer) is answer


def test_the_minted_print_is_a_graphic_record_flagged_as_assumed():
    parts = concept_scan.parts_from_concept(
        _answer(_panel("FRONT PANEL", "green printed plywood")), "bdab4adf-3340-40M&S")
    assert len(parts) == 2
    board, print_line = parts
    assert board["concept_kind"] == "fabricated"
    assert print_line["concept_kind"] == "graphic"
    assert print_line.get("concept_print_assumed") is True
    assert print_line.get("blank_length_mm") in (None, 0), "a print is not a blank to cut"
    flag = " ".join(print_line["review_flags"])
    assert "print ASSUMED on FRONT PANEL" in flag
    assert "'green printed plywood'" in flag and "plywood PLYWOOD" not in flag
    assert "Confirm the print method" in flag


def test_the_prompt_asks_for_print_as_its_own_line():
    assert concept_scan.CONCEPT_PROMPT_VERSION == "c4"
    assert "PRINT IS ALWAYS ITS OWN LINE" in concept_scan._PROMPT


# ── D-367: a blank that fits no sheet as given is costed turned ─────────────────────────

def _back_panel(length, width):
    return {"part_number": "BDAB4ADF-3340-40M-S-CPT01", "description": "TALL BACK PANEL",
            "normalized_material": "PLYWOOD", "normalized_thickness_mm": 18, "quantity": 1,
            "blank_length_mm": length, "blank_width_mm": width}


def test_a_back_panel_given_across_the_sheet_is_turned_to_fit():
    """17:30 book: 600 x 1800 nested on no plywood sheet and went through at £0."""
    part = _back_panel(600, 1800)
    me = estimator.estimate_material(part)
    assert (me["blank_length_mm"], me["blank_width_mm"]) == (1800.0, 600.0)
    assert me["stock_estimate"]["candidate_sheet_size_mm"] == [3050, 1525]
    assert me["stock_estimate"]["parts_per_sheet"] == 2
    assert part["blank_turned_to_fit"] == {"as_given": [600.0, 1800.0],
                                           "costed": [1800.0, 600.0]}
    assert any("TURNED TO FIT" in str(f) for f in part["review_flags"])


def test_a_blank_that_already_fits_is_never_turned():
    part = _back_panel(1200, 600)
    me = estimator.estimate_material(part)
    assert (me["blank_length_mm"], me["blank_width_mm"]) == (1200.0, 600.0)
    assert "blank_turned_to_fit" not in part


def test_a_blank_that_fits_neither_way_is_left_for_the_oversize_rule():
    part = _back_panel(4000, 2000)
    estimator.estimate_material(part)
    assert "blank_turned_to_fit" not in part


# ── D-368: a lid, flap or door brings its hinges ────────────────────────────────────────

def _bought(name, quantity=1):
    return {"name": name, "kind": "bought_in", "sighted_material": name.lower(),
            "material_guess": "", "assumed_blank_mm": {}, "quantity": quantity}


def test_a_lid_with_no_hinge_gets_hinges_assumed():
    """17:30 book: a LID PANEL and no hinge, so nothing held the lid on."""
    answer = concept_scan._with_implied_fittings(_answer(
        _panel("LID PANEL", "plywood", 564, 564), _bought("CASTOR", 4)))
    hinge = [p for p in answer["parts"] if p["name"] == "HINGE"]
    assert len(hinge) == 1 and hinge[0]["kind"] == "bought_in"
    per = config.CONCEPT_IMPLIED_FITTINGS[0]["per_part"]
    assert hinge[0]["quantity"] == per


def test_a_listed_hinge_is_never_added_again():
    answer = _answer(_panel("LID PANEL", "plywood"), _bought("LID HINGE", 2))
    assert concept_scan._with_implied_fittings(answer) is answer


def test_a_unit_without_a_lid_gets_no_hinge():
    answer = _answer(_panel("BASE", "plywood"), _bought("CASTOR", 4))
    assert concept_scan._with_implied_fittings(answer) is answer


def test_the_assumed_hinge_reaches_the_book_flagged():
    parts = concept_scan.parts_from_concept(
        _answer(_panel("LID PANEL", "plywood", 564, 564)), "bdab4adf-3340-40M&S")
    hinge = next(p for p in parts if "HINGE" in p["description"].upper())
    assert hinge["concept_kind"] == "bought_in"
    assert hinge.get("concept_fitting_assumed") is True
    flag = " ".join(hinge["review_flags"])
    assert "HINGE ASSUMED" in flag and "LID PANEL" in flag and "Confirm the fitting" in flag


def test_the_rule_and_its_count_live_in_config():
    rule = config.CONCEPT_IMPLIED_FITTINGS[0]
    assert {"part_words", "fitting_words", "fitting", "per_part"} <= set(rule)
