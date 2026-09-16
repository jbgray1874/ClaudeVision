"""Joinery rates come from a joinery job — and the set-up comes out of them first.

"No edge banding, no machining saw/spindle, no bench work time, CNC setup not amortised"
— Tony Ford, reviewing the engine's 11908-21 book against his own.

Every joinery throughput the engine held was a GUESS borrowed from a neighbouring
department, because no joinery job had ever been measured. His Labour tab is the first
measurement — and it states HOURS PER ORDER, which is not what the engine needs.

THE FIRST ATTEMPT DIVIDED THOSE HOURS BY HIS QUANTITY AND SHIPPED THE RESULT. That buried
the set-up inside the per-part rate, and the workbook then added its own set-up row on top:
a faced-board job paid for its set-up twice, and its quantity breaks had nothing left to
amortise. Which is Tony's "CNC setup not amortised", arriving from the other side.

THE EVIDENCE SEPARATES THEM. Subtract the set-up this engine ALREADY holds for each
department — OPERATION_SETUP_MIN, read off the Estimate template's own rate rows — and every
one of the five falls on a whole number:

    dept   his hours   set-up   run hours   RUN RATE      the guess it replaces
    CNCJ      4.4167     15 m      4.1667   12 /hr        30
    EDGE      4.6667     30 m      4.1667   12 /hr        30
    MC J      4.6667     30 m      4.1667   12 /hr        no row at all
    BENC     25.5000     30 m     25.0000    2 /hr        79   (forty times too fast)
    PACJ      2.7500     15 m      2.5000   20 /hr        99

Five departments, five exact integers, against a table written from the template long
before his sheet was read. One would be a coincidence; five is his sheet and this engine
using one convention — which is what makes this a measurement rather than a curve fit.

STILL A SCOPED PILOT. One job is one job: these apply to the family they were measured on
and widen when a second job or the department confirms them.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                         # noqa: E402

# (register key, department code, his stated hours, the guess it replaces)
_HIS_SHEET = (
    ("joinery_cnc_parts_per_hour",          "CNCJ",  4.4167, 30),
    ("joinery_edge_banding_parts_per_hour", "EDGE",  4.6667, 30),
    ("joinery_machining_parts_per_hour",    "MC J",  4.6667, None),
    ("joinery_bench_parts_per_hour",        "BENC", 25.5,    79),
    ("joinery_pack_parts_per_hour",         "PACJ",  2.75,   99),
)


def test_every_rate_is_his_hours_MINUS_SETUP_divided_by_his_quantity():
    """THE DECOMPOSITION, re-derived from the engine's OWN set-up table rather than from the
    numbers written beside it — so config's call sites and OPERATION_SETUP_MIN cannot drift
    apart without this failing."""
    qty = config.SHOP_STATED["joinery_rates_measured_at_quantity"]
    assert qty == 50
    for key, code, hours, _ in _HIS_SHEET:
        run_h = hours - config.OPERATION_SETUP_MIN[code] / 60.0
        assert abs(config.SHOP_STATED[key] - (qty / run_h)) < 0.001, key


def test_all_five_land_on_whole_numbers_which_is_why_it_is_evidence():
    """Five departments, five exact integers, against a set-up table written from the
    template long before Tony's sheet was read. One would be a coincidence; five is the two
    documents using one convention, and THAT is what makes this a measurement rather than a
    curve fit."""
    qty = config.SHOP_STATED["joinery_rates_measured_at_quantity"]
    for key, code, hours, _ in _HIS_SHEET:
        rate = qty / (hours - config.OPERATION_SETUP_MIN[code] / 60.0)
        # 1e-3: his hours are stated to four places on the sheet, so the exact
        # integer is reached from the exact hours, not from the rounding of them.
        assert abs(rate - round(rate)) < 1e-3, (key, rate)
        assert config.SHOP_STATED[key] == round(rate), key


def test_the_setup_is_not_buried_in_the_rate():
    """THE DEFECT THIS REPLACES. Shipping the hours whole buried the set-up inside the
    per-part rate AND left the workbook adding its own set-up row on top — so a faced-board
    job paid for its set-up twice and its breaks had nothing left to amortise. Every rate
    must therefore be FASTER than the hours-whole figure it replaced."""
    qty = config.SHOP_STATED["joinery_rates_measured_at_quantity"]
    for key, code, hours, _ in _HIS_SHEET:
        assert config.SHOP_STATED[key] > qty / hours, key
    assert "set-up charged separately" in config.SHOP_STATED["joinery_rates_status"]


def test_the_job_these_were_measured_on_is_named():
    assert config.SHOP_STATED["joinery_rates_measured_on_job"] == "11908-21"


def test_each_one_is_attributed_to_tony_and_declares_it_is_derived():
    """A figure nobody stated must never print as one somebody did."""
    for key, _code, _hours, _guess in _HIS_SHEET:
        src = config.shop_stated_source(key)
        assert "Tony Ford" in src and "11908-21" in src, (key, src)
        ev = config.SHOP_STATED_PROVENANCE[key]["evidence"]
        assert ev.startswith("DERIVED by this engine"), (key, ev)
        assert "set-up" in ev, "the split has to travel with the figure"
        assert "once per order" in ev, "and so does how set-up is charged"
        assert "one job" in ev, "and so does the sample size"
        assert str(config.SHOP_STATED["joinery_rates_measured_at_quantity"]) in ev


def test_bench_work_was_the_forty_fold_error():
    """Stated as its own test because it is the single biggest correction in the set, and
    a future edit that quietly moves it back toward the metal bench figure should fail
    here rather than in an estimator's inbox."""
    bench = config.SHOP_STATED["joinery_bench_parts_per_hour"]
    assert bench == 2.0, bench
    assert 79 / bench > 30, "the guess it replaces was more than thirty times too fast"


def test_the_workbook_table_takes_the_register_figures():
    """The literal table stays readable as a table, but the register governs — changing
    the literal has to change nothing, which is the point of having a register."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    for row, key in (("CNC Joinery",        "joinery_cnc_parts_per_hour"),
                     ("Edge Banding",       "joinery_edge_banding_parts_per_hour"),
                     ("Bench Work Joinery", "joinery_bench_parts_per_hour"),
                     ("Packing Joinery",    "joinery_pack_parts_per_hour")):
        assert f'"{row}"' in src, row
        assert key in src, f"{row} must read {key} from the register"


def test_the_machining_figure_is_recorded_even_though_no_row_emits_it_yet():
    """MC J is 4.67 of his hours and the engine emits no such operation at all — which is
    exactly his "no machining saw/spindle". The measurement is banked here so that when
    the operation is emitted it arrives with a real figure rather than another guess."""
    assert config.SHOP_STATED["joinery_machining_parts_per_hour"] > 0
    assert "does not yet emit" in \
        config.SHOP_STATED_PROVENANCE["joinery_machining_parts_per_hour"]["evidence"]


# ── the edging: we hold the rate, we do not hold the metreage ────────────────────────────
#
# "Not all materials calculated no ABS edging Allowed" — Tony's first finding. The pack
# states no edging spec anywhere (his line quotes the Egger reference from the spec book,
# not from the drawing), so the engine could not mint the material without inventing it.
# His sheet states both halves, and only one of them generalises.

def test_his_edging_line_is_reproduced_from_the_register():
    """5 m at £0.35 with his 4% scrap is the £1.82 on his sheet."""
    import stated_prices
    rate = stated_prices.resolve(config.FACED_BOARD_EDGING_CODE,
                                 "ABS edging for faced board")
    assert rate["gbp"] == 0.35
    assert round(5 * rate["gbp"] * 1.04, 2) == 1.82


def test_the_rate_says_whose_it_is_and_that_it_is_not_a_live_price():
    import stated_prices
    label = stated_prices.resolve(config.FACED_BOARD_EDGING_CODE, "")["label"]
    assert "Tony Ford" in label and "11908-21" in label
    assert "not a live system price" in label


def test_the_metreage_is_never_taken_from_the_drawn_perimeter():
    """THE RULE THAT MATTERS. Only the VISIBLE edges are banded, and which those are is a
    judgement about the product rather than a number on the drawing. Tony bands 5 m where
    the drawn perimeter is far more, so a rule that banded every drawn edge would overcharge
    every joinery job by the difference — on his own tray, £5.18 against £1.82."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "if EVERY edge were" in src, "the ask must say the figure is an upper bound"
    assert "tell us the banded metres" in src, "and ask for the real one"


def test_the_edging_code_is_named_once():
    """The ask and the register read the same constant, so they cannot drift apart."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "FACED_BOARD_EDGING_CODE" in src
    assert config.FACED_BOARD_EDGING_CODE in config.ESTIMATOR_STATED_PRICES


# ── a scoped pilot, not a joinery constant ───────────────────────────────────────────────
#
# The first version of this applied Tony's figures to every joinery job at every quantity.
# Review caught it immediately, and it is the SAME defect he reported arriving from the
# other side: his hours are PER ORDER and contain both run time and whatever setup each
# department did once. One job is one equation in two unknowns.

def test_the_setup_is_known_and_points_at_the_table_that_holds_it():
    """It WAS recorded as unknown, correctly, when one job looked like one equation in two
    unknowns. It is not unknown any more: the engine's own set-up table solves it, and the
    five whole numbers are the proof. A department name, not a number — the minutes live in
    one place and the workbook charges them once per order."""
    assert "OPERATION_SETUP_MIN" in config.SHOP_STATED["joinery_setup_source"]
    assert "joinery_setup_min_per_department" not in config.SHOP_STATED, \
        "superseded by the decomposition — a stale UNKNOWN reads as an open question"


def test_the_figures_declare_their_scope_and_their_status():
    assert "MFMDF" in config.SHOP_STATED["joinery_rates_scope"]
    assert "pilot" in config.SHOP_STATED["joinery_rates_status"]


def test_the_overlay_only_fires_on_the_family_it_was_measured_on():
    """Outside faced board the old UNMEASURED guesses stand. An honest 'we do not know'
    beats another department's number wearing joinery's name."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "_faced_board_job" in src
    i = src.index("_faced_board_job = any(")
    j = src.index('joinery_pack_parts_per_hour', i)
    gate = src[i:j]
    assert "MFMDF" in gate and "MFC" in gate
    assert "if _faced_board_job:" in gate, "the overlay must sit inside the gate"


def test_the_register_and_the_code_agree_about_scope():
    """D-045's first version said 'one job is one job' in its evidence and 'generic
    (joinery)' in its scope. Both cannot be true, and a register that contradicts itself is
    worse than no register."""
    reg = open(os.path.join(os.path.dirname(__file__), "..", "docs", "CHANGE_REGISTER.md"),
               encoding="utf-8").read()
    row = [ln for ln in reg.splitlines() if ln.startswith("| D-045 ")]
    assert row, "D-045 must exist"
    assert "generic (joinery)" not in row[0], \
        "the code scopes these to faced board; the register may not call them generic"


# ── the set-up convention holds on a second sheet, and a metal one ───────────────────────
#
# Howard Thurley's 7332-01 (15 Sep 2026, quantity 6) decomposes the same way against the
# same table — and on this one the decomposition lands on three figures he had already
# stated in plain English, weeks before anybody looked at his hours.

_HOWARD_7332_HOURS = {"WELD": 3.5, "DRES": 2.5, "MANM": 4.25}
_HOWARD_SAID = {"WELD": 30.0, "DRES": 20.0, "MANM": 40.0}   # "0.5 hr", "20 min", "40 minutes"


def test_the_convention_reproduces_what_howard_told_us_in_words():
    """Two estimators, two product families, two jobs, one convention. This is what makes
    the set-up model SHOP-WIDE rather than a joinery finding: on Tony's sheet the proof is
    five whole numbers; on Howard's it is three figures he had independently said out loud."""
    for code, hours in _HOWARD_7332_HOURS.items():
        run_h = hours - config.OPERATION_SETUP_MIN[code] / 60.0
        assert abs(run_h * 60 / 6 - _HOWARD_SAID[code]) < 0.001, code


def test_the_second_confirmation_is_written_down_where_the_rates_live():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "config.py"),
               encoding="utf-8").read()
    assert "CONFIRMED ON A SECOND SHEET, AND A METAL ONE" in src
    assert "his \"0.5 hr\"" in src and "his \"40 minutes\"" in src
    # and it must not overclaim: the RATES are still a joinery pilot
    i = src.index("CONFIRMED ON A SECOND SHEET")
    assert "remain a" in src[i:i + 1400] and "pilot" in src[i:i + 1400]
