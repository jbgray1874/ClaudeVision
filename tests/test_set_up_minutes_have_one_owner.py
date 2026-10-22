"""Set-up is a batch cost, and the minutes need one owner.

SET-UP DOES NOT SCALE WITH QUANTITY. One unit and a hundred pay the same ten or fifteen or
thirty minutes per tooling group; only the per-unit SHARE falls, as
`setup_min / 60 / order_qty x rate`. That is already how the sheet behaves, and it is the whole
of the quantity-break story: on one real pack at 7 off, GBP 46.41 of GBP 83.77 labour was
set-up against GBP 37.36 of run, so the same job at 100 off sheds about GBP 43 a unit without a
single rate moving.

WHAT WAS MISSING WAS THE OWNER, and the drift had already started. The figure lived in
ACRYLIC_OP_DRIVERS, in RATE_CARD, and in the Estimate template's rate rows — and acrylic laser
read 5 minutes in one and 10 in another. A department cannot have its rate on one book and its
set-up invented somewhere else.

These tests pin the rule, not any job: no part numbers, no drawing references.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                           # noqa: E402
from sheet_steel_costing import RATE_CARD, setup_min_for                # noqa: E402


def test_every_rate_card_department_has_a_set_up_in_the_one_table():
    """A department that can be charged must be able to say what its set-up is."""
    for _title, (_rate, _setup, _dept) in RATE_CARD.items():
        assert _dept in config.OPERATION_SETUP_MIN, f"{_title} ({_dept}) has no set-up entry"
        assert setup_min_for(_dept) is not None


def test_the_rate_card_takes_its_minutes_from_that_table():
    """One number, not two that happen to agree today."""
    for _title, (_rate, _setup, _dept) in RATE_CARD.items():
        assert _setup == config.OPERATION_SETUP_MIN[_dept], _title


def test_the_acrylic_drivers_no_longer_carry_their_own_copy():
    """THE DRIFT THAT WAS ALREADY THERE. Five of six agreed with the rate card and the sixth did
    not — acrylic laser read 5 minutes against the card's 10."""
    for _key, _dept in (("laser_setup_min", "LASA"), ("linebend_setup_min", "LINE"),
                        ("glue_setup_min", "GLUE"), ("flame_setup_min", "MANA"),
                        ("diamond_polish_setup_min", "DPOL"), ("peel_setup_min", "MANA")):
        assert config.ACRYLIC_OP_DRIVERS[_key] == float(config.OPERATION_SETUP_MIN[_dept]), _key


def test_the_ladder_is_book_then_config_then_an_explicit_nil():
    """Same ladder as material: the labour book wins where it carries a set-up, the table is the
    offline fallback, and a department in neither is a nil rather than a guessed fifteen."""
    assert setup_min_for("CNC", book_setup_min=22) == 22.0, "the book wins when it has a figure"
    assert setup_min_for("CNC") == config.OPERATION_SETUP_MIN["CNC"], "config is the fallback"
    assert setup_min_for("NO_SUCH_DEPARTMENT") is None, "and an unknown department is a nil"
    assert setup_min_for("") is None
    assert setup_min_for(None) is None


def test_it_answers_by_department_code_or_by_rate_card_title():
    """Callers hold one or the other; neither should have to convert."""
    assert setup_min_for("CNCJ") == setup_min_for("CNC Joinery")
    assert setup_min_for("LASA") == setup_min_for("Laser (Acrylic)")
    assert setup_min_for("cnc joinery") == setup_min_for("CNC Joinery"), "and case is not a trap"


def test_quantity_is_not_a_parameter_and_must_not_become_one():
    """A BATCH COST. If set-up ever varies with quantity here, the amortisation downstream is
    being applied to a figure that has already been divided, and the saving is counted twice."""
    import inspect
    _sig = inspect.signature(setup_min_for)
    assert not any(_p in _sig.parameters for _p in ("qty", "quantity", "order_qty")), (
        "set-up is the same minutes at 1 off and at 100; only the share falls")


def test_the_departments_the_template_carries_are_all_covered():
    """ELEVEN DEPARTMENTS EXISTED ON THE TEMPLATE AND NOT ON THE ENGINE'S CARD, so the engine
    could not cost or check them — two of them, welding and wet spray, are used on live packs."""
    for _dept in ("WELD", "SPRY", "TBEN", "SAW", "SPOT", "PUNC", "ROBO", "ROLL", "SALV",
                  "TUBE", "PINR"):
        assert setup_min_for(_dept) is not None, f"{_dept} is on the sheet and has no set-up"


def test_the_share_falls_with_quantity_but_the_minutes_do_not():
    """The arithmetic Tim is asking about, stated once: same minutes, smaller share."""
    _rate, _setup, _ = RATE_CARD["CNC"]
    _cost = lambda q: ((_rate / 60.0) * _setup) / q          # noqa: E731
    assert setup_min_for("CNC") == _setup
    assert _cost(1) > _cost(7) > _cost(100)
    assert abs(_cost(1) / 100 - _cost(100)) < 1e-9, "the share is strictly one over quantity"
