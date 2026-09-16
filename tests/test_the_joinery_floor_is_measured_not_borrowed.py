"""Joinery throughputs come from a joinery job, not from the department next door.

"No edge banding, no machining saw/spindle, no bench work time, CNC setup not amortised"
— Tony Ford, reviewing the engine's 11908-21 book against his own.

Every joinery throughput the engine held was a GUESS borrowed from a neighbouring
department, because no joinery job had ever been measured. His sheet is the first
measurement, and the guesses were not close:

    dept   his hours   min/unit   parts/hour      the guess we held
    CNCJ      4.4167       5.30      11.3208      30   (2.6x too fast)
    EDGE      4.6667       5.60      10.7143      30   (2.8x too fast)
    MC J      4.6667       5.60      10.7143      no row at all
    BENC     25.5000      30.60       1.9608      79   (40.3x too fast)
    PACJ      2.7500       3.30      18.1818      99   (5.4x too fast)

Bench work is 25.5 of his 42 hours run forty times too fast. That single number is what
"no bench work time" looks like from the estimator's side, and most of the gap between
his £57.09 and ours.

DERIVED, AND IT HAS TO SAY SO. His sheet states HOURS PER ORDER at a quantity of 50; the
engine needs parts/hour, so each figure is his hours divided by his quantity. That is
arithmetic on a stated fact, not a stated fact — a per-order element inside those hours
would inflate the per-part figure, and one job is one job. Both caveats live in the
provenance, so nothing downstream can print these as though a department had stated a
rate.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                         # noqa: E402

# (register key, his stated hours, the guess it replaces)
_HIS_SHEET = (
    ("joinery_cnc_parts_per_hour",          4.4167, 30),
    ("joinery_edge_banding_parts_per_hour", 4.6667, 30),
    ("joinery_machining_parts_per_hour",    4.6667, None),   # no row exists yet
    ("joinery_bench_parts_per_hour",       25.5,    79),
    ("joinery_pack_parts_per_hour",         2.75,   99),
)


def test_every_figure_is_his_hours_divided_by_his_quantity():
    """The arithmetic, reproduced from his sheet rather than trusted."""
    qty = config.SHOP_STATED["joinery_rates_measured_at_quantity"]
    assert qty == 50
    for key, hours, _ in _HIS_SHEET:
        assert abs(config.SHOP_STATED[key] - (qty / hours)) < 0.001, key


def test_the_job_these_were_measured_on_is_named():
    assert config.SHOP_STATED["joinery_rates_measured_on_job"] == "11908-21"


def test_each_one_is_attributed_to_tony_and_declares_it_is_derived():
    """A figure nobody stated must never print as one somebody did."""
    for key, _, _ in _HIS_SHEET:
        src = config.shop_stated_source(key)
        assert "Tony Ford" in src and "11908-21" in src, (key, src)
        ev = config.SHOP_STATED_PROVENANCE[key]["evidence"]
        assert ev.startswith("DERIVED by this engine"), (key, ev)
        assert "setup" in ev, "the per-order caveat has to travel with the figure"
        assert "one job" in ev, "and so does the sample size"
        assert str(config.SHOP_STATED["joinery_rates_measured_at_quantity"]) in ev


def test_bench_work_was_the_forty_fold_error():
    """Stated as its own test because it is the single biggest correction in the set, and
    a future edit that quietly moves it back toward the metal bench figure should fail
    here rather than in an estimator's inbox."""
    bench = config.SHOP_STATED["joinery_bench_parts_per_hour"]
    assert 1.5 < bench < 2.5, bench
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

def test_setup_is_recorded_as_unknown_not_as_zero():
    """None, not 0.0. Zero is a claim — that the departments set up instantly — and it is
    the claim that would silently bake the setup into the per-unit rate."""
    assert config.SHOP_STATED["joinery_setup_min_per_department"] is None
    ev = config.SHOP_STATED_PROVENANCE["joinery_setup_min_per_department"]["evidence"]
    assert "UNKNOWN" in ev
    assert "ASK TONY" in ev, "an unknown with no question attached never becomes known"


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
