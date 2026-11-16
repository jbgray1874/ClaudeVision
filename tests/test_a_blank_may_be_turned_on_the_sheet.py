"""24 a sheet as drawn, 26 with length and width exchanged, and the template cannot rotate.

    "Line 84 – AI Yield 24 Per Sheet – if Component, Exchange Length for Width and Vice
     Versa   Yield is 26 Per Sheet"           — Howard Thurley, 0355255, 9 Sep 2026

He is right, and the fix cannot live in the nest formula: the workbook recomputes the yield
itself from the dims the engine writes, by the same fixed-orientation rule (K38 for steel,
J51 for plastics — neither rotates). So the engine tries both orientations and, where the
turned one nests better, WRITES THE BLANK TURNED — the sheet then reaches 26 by its own
arithmetic, and the JSON and the workbook still agree, which is the invariant the whole
nesting area exists to keep.

NEVER FOR A BLANK WITH A DIRECTION. A brushed or grained panel nested sideways is a panel
the customer rejects, and no yield pays for that. Tokens (config.DIRECTIONAL_FINISH_TOKENS),
never part numbers, so a job nobody has seen yet is judged by the same rule and estimating
can extend the list.

AND ONLY THE SHEET PLASTICS, FOR NOW. A steel blank turned changes which way its bends
run against the rolling direction; a faced board turned runs its oak the wrong way across
the panel. Both are shop questions, not yields to bank — they stay drawn-orientation until
the shop rules. Acrylic and its siblings have no grain, which is Howard's case.

AND NEVER WITHOUT THE CALLER'S CONSENT. A call site that takes parts_per_sheet without
owning the written dims would put a rotated yield beside unrotated dimensions — the exact
disagreement this prevents. No part handed over, no rotation.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator                                                     # noqa: E402


def _l_stand(**over):
    part = {"part_number": "10975-02-A01", "description": "L-STAND",
            "normalized_material": "ACRYLIC", "normalized_thickness_mm": 2.0,
            "quantity": 1, "blank_length_mm": 760.25, "blank_width_mm": 210.0}
    part.update(over)
    return part


def test_howards_l_stand_nests_26_with_the_blank_turned():
    out = estimator.estimate_material(_l_stand())
    se = out["stock_estimate"]
    assert se["parts_per_sheet"] == 26, "his 26, not our 24"
    assert se["rotated"] is True


def test_the_blank_is_written_turned_so_the_sheet_agrees():
    """The workbook recomputes the nest from the written dims. 26 in the JSON beside
    760.25 x 210 on the sheet would be 26 claimed and 24 charged."""
    out = estimator.estimate_material(_l_stand())
    assert (out["blank_length_mm"], out["blank_width_mm"]) == (210.0, 760.25)


def test_the_turn_is_named_on_the_record():
    part = _l_stand()
    estimator.estimate_material(part)
    assert any("NESTED TURNED" in f for f in part.get("review_flags", [])), \
        "a changed orientation somebody may have to explain is written down"


def test_a_brushed_blank_is_never_turned():
    out = estimator.estimate_material(_l_stand(description="L-STAND BRUSHED FACE"))
    se = out["stock_estimate"]
    assert se["rotated"] is False
    assert se["parts_per_sheet"] == 24
    assert (out["blank_length_mm"], out["blank_width_mm"]) == (760.25, 210.0)


def test_every_directional_token_guards_not_just_brush():
    import config
    for token in config.DIRECTIONAL_FINISH_TOKENS:
        out = estimator.estimate_material(_l_stand(finish=f"{token.title()} finish"))
        assert (out["stock_estimate"] or {}).get("rotated") is False, token


def test_no_part_handed_over_means_no_rotation():
    """select_sheet_size called bare (the sites that do not own the written dims) must
    answer fixed-orientation, or their yield disagrees with the sheet."""
    se = estimator.select_sheet_size("ACRYLIC", 760.25, 210.0)
    assert se["parts_per_sheet"] == 24
    assert not se.get("rotated")


def test_a_worse_turn_is_not_taken():
    """Rotation is an option, not a policy — the drawn orientation stands unless the turn
    actually yields more."""
    # 200 x 100 on 3050 x 2050 J51: drawn INT(3050/220)x INT(2045/120) = 13x17 = 221;
    # turned INT(3050/120) x INT(2045/220) = 25x9 = 225 -> turned wins. Use a square-ish
    # blank where the turn buys nothing instead:
    se = estimator.select_sheet_size("ACRYLIC", 300.0, 300.0, part={"description": "TILE"})
    assert not se.get("rotated"), "a square cannot be improved by turning"


# ── the one register ─────────────────────────────────────────────────────────────────────

def test_every_stated_shop_figure_lives_in_shop_stated():
    """"can we put these into a central area that is easy to identify and change if
    needed" — James. Linebend lived in ACRYLIC_OP_DRIVERS and the acrylic laser rate in
    wb_populate's throughput table, each with its own attribution comment: three homes for
    one kind of fact. The values now live in SHOP_STATED and the old homes read from it."""
    import config
    assert config.SHOP_STATED["linebend_min_per_bend"] == 0.5
    assert config.SHOP_STATED["laser_acrylic_parts_per_hour"] == 95.0
    assert config.ACRYLIC_OP_DRIVERS["min_per_linebend"] is config.SHOP_STATED[
        "linebend_min_per_bend"] or config.ACRYLIC_OP_DRIVERS["min_per_linebend"] == 0.5
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "laser_acrylic_parts_per_hour" in src, \
        "the register's value overwrites the table's literal"
    assert '_THROUGHPUT_DEFAULTS["Laser (Acrylic)"] = float(' in src, \
        "the overlay is what makes the register the owner — the literal stays only so " \
        "the table parses as a table for the rate inventory"


def test_a_steel_and_a_board_are_not_turned():
    """The rolling direction and the face grain are the shop's to rule on, not yields to
    bank quietly. Drawn orientation until then."""
    se = estimator.select_sheet_size("MILD STEEL", 500.0, 290.0, part={"description": "PLATE"})
    assert not se.get("rotated")
    se = estimator.select_sheet_size("MFC", 1434.0, 748.0, part={"description": "PANEL"})
    assert not se.get("rotated")
