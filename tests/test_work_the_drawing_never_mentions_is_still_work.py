"""Two costs the pack does not draw, and the shop pays for both.

    "Line 85 – Drawing doesn't annotate – material is brushed prior to sending to platers,
     op. for Manual Labour (Metal) 40 Minutes"
    "** Delivery to & from Platers from Transport Dept. For Ref. £120.00 Pallet Network -
     £20.00 per Unit"                        — Howard Thurley, SDI estimating, 9 Sep 2026

Both were carried as prose. The brushing was a review flag, on the reasoning that forty
minutes nobody drew is an invention. The freight was a sentence on the plating line, on the
sound reasoning that the plating figure must equal what the PLATER charges so it can be
checked against the plater's own quote.

Each argument was half right, and each drew the wrong conclusion from its right half.

Forty minutes nobody drew AND nobody mentioned would be an invention. An estimator has
mentioned it, with a duration. Leaving it off is not caution, it is under-charging — the
direction nobody notices, because a quote that is too low is accepted. And the flag reached
neither deliverable, so "named instead of costed" was not even naming it.

The plating line does have to equal the plater's quote. That is an argument for the freight
being on a DIFFERENT line, not for it being on no line at all: "kept separate" and "not
charged" are not the same thing, and what shipped was the second.

BOTH INHERIT, AND BOTH SHOULD. Any job that sends work to a platers pays to get it there and
back, and any material that goes in the tank is prepared first. They are how SDI works, so
they live in config — unlike the £250 and the tube bend, which are decisions about one stand
and live in that stand's own file.

ONCE PER CONSIGNMENT, NOT ONCE PER MEMBER. What goes to the platers is the weldment. Forty
minutes against each of 7332-01-101's six members is four hours of linishing on one stand,
which is how a defensible figure becomes an absurd one.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                            # noqa: E402
from estimator import estimate_process_times                             # noqa: E402


def _weldment(finish="PLATED", **over):
    part = {"part_number": "7332-01-101", "description": "FRAME WELDMENT",
            "normalized_material": "MILD_STEEL", "normalized_finish": finish,
            "textual_operations": ["welding", "dress_welds", "assembly"], "quantity": 1}
    part.update(over)
    return part


def _times(part):
    return estimate_process_times(part, 6)["run_times_min_per_unit"]


# ── brushed before the platers ───────────────────────────────────────────────────────────

def test_a_plated_weldment_is_brushed_and_it_is_costed():
    assert _times(_weldment())["manual_labour_metal"] == 40.0


def test_it_is_booked_once_not_once_per_member():
    """Six members would be four hours. The consignment is the weldment."""
    t = _times(_weldment(child_parts=["001", "002", "003", "004", "005", "008"]))
    assert t["manual_labour_metal"] == 40.0


def test_a_plated_leaf_is_named_and_not_charged():
    """The limit, stated rather than hidden: a plated part that is not the weldment gets the
    question, not the forty minutes. That job is under-charged by this operation and the
    line says so."""
    leaf = {"part_number": "7332-01-008", "description": "BACK PANEL",
            "normalized_material": "MILD_STEEL", "normalized_finish": "PLATED",
            "textual_operations": ["laser_cutting"], "quantity": 1}
    t = _times(leaf)
    assert "manual_labour_metal" not in t
    assert any("brushes material" in str(f) for f in leaf.get("review_flags") or [])


def test_an_unplated_weldment_is_not_brushed():
    """12349-02 is powder coated and goes nowhere near a plater."""
    assert "manual_labour_metal" not in _times(_weldment(finish="POWDER COATED RAL9005"))


def test_the_line_says_the_drawing_does_not_say_it():
    part = _weldment()
    estimate_process_times(part, 6)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "THE DRAWING DOES NOT ANNOTATE THIS" in flags
    assert "Howard Thurley" in flags
    assert "take it off" in flags


def test_it_can_be_switched_back_to_a_flag(monkeypatch):
    """`enabled: False` returns to naming it without costing it — the state it was in, kept
    reachable because Howard called it a grey area and may rule it out."""
    monkeypatch.setitem(config.BRUSH_BEFORE_PLATE, "enabled", False)
    part = _weldment()
    assert "manual_labour_metal" not in _times(part)
    assert any("brushes material" in str(f) for f in part.get("review_flags") or [])


def test_the_minutes_are_one_config_edit(monkeypatch):
    monkeypatch.setitem(config.BRUSH_BEFORE_PLATE, "minutes_per_unit", 25.0)
    assert _times(_weldment())["manual_labour_metal"] == 25.0


# ── freight to the platers and back ──────────────────────────────────────────────────────

def test_the_freight_figure_is_register_data_scoped_to_its_own_job():
    """The £120/£20 was 7332-01's own transport quote. In config it was every plated
    job's freight — the £250 fault in a smaller coat — so it moved to the register,
    job_only, and another job's plated route raises the line UNPRICED naming SDI
    transport instead of borrowing it."""
    from estimator import plater_freight_for_job
    entry = plater_freight_for_job(("7332-01",))
    assert entry and entry["amount"] == 120.0
    assert "transport department" in entry["source_reference"].lower()
    assert plater_freight_for_job(("8888-02",)) is None
    assert "freight_gbp_per_order" not in config.PLATING_LOGISTICS


def test_the_engine_mints_a_freight_line_beside_the_plating():
    """It is a line, not a sentence. The code is checked here rather than by running a whole
    job: what matters is that a separate PLATERFREIGHT part is created, priced per order and
    divided by the order quantity, and that the plating line is left alone."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert 'PLATERFREIGHT' in src
    assert "_fr_unit = round(_fr_order / _fq, 2)" in src
    assert "AND GETTING IT THERE AND BACK IS A LINE, NOT A SENTENCE" in src


def test_the_plating_line_is_still_held_equal_to_the_platers_quote():
    """THE RULE THE FREIGHT MUST NOT BREAK. The reason it was kept off the plating line is
    good and it survives: an estimator has to be able to check that line against the quote."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "AND IT IS NOT ADDED TO THIS LINE, DELIBERATELY" in src


def test_it_only_exists_where_there_is_plating():
    """A job with no plating never mints a plating placeholder, so it never reaches the
    freight line either — the two are minted together, deliberately. And the route
    inherits while the money does not: the unpriced branch exists beside the priced one."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    plate_at = src.index('_pstub["_plating_placeholder"] = True')
    freight_at = src.index('_fr_code = "PLATERFREIGHT"')
    assert plate_at < freight_at
    assert "THE ROUTE INHERITS; THE MONEY DOES NOT" in src
    assert "plater_freight_awaiting_quote" in src
