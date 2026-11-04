"""A fold is a fold whichever way it runs across the sheet.

12693-01-03M is a 1.5 mm worktop skin: a down-stand and a return on all four sides, so eight
bend lines on its BENDLINES layer, four horizontal and four vertical. The flat reader counted
four. `_extract_bend_data` collected the vertical lines and then counted only the distinct
horizontal axes, so every fold that ran up the sheet was dropped from the press brake.

THE WORSE CASE IS ONE BEND. A flat whose only fold runs vertically read zero bends, and a
measured zero on a declared bend layer is exactly what `dxf_can_rule_out_folding` accepts as
proof the part does not fold. So the fold the drawing shows was stripped.

WHAT STAYS. A bend line the exporter broke around a cut-out is still one fold; the count is of
AXES, not of line entities, and that rule was right.

The same flats are named `..._REV_A`. Split on underscores, "REV" and "A" are two tokens and
the reader's one-token match read no revision.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

ezdxf = pytest.importorskip("ezdxf")

from dxf_reader import _parse_filename, extract_flat_pattern_data   # noqa: E402
from drawing_job_merge import dxf_can_rule_out_folding              # noqa: E402


def _flat(tmp_path: Path, name: str, outline, bends) -> Path:
    doc = ezdxf.new()
    doc.header["$INSUNITS"] = 4
    doc.layers.add("SLD-0")
    doc.layers.add("BENDLINES")
    msp = doc.modelspace()
    for a, b in zip(outline, outline[1:] + outline[:1]):
        msp.add_line(a, b, dxfattribs={"layer": "SLD-0"})
    for a, b in bends:
        msp.add_line(a, b, dxfattribs={"layer": "BENDLINES"})
    path = tmp_path / name
    doc.saveas(path)
    return path


SQUARE = [(0, 0), (1250, 0), (1250, 1250), (0, 1250)]


def test_a_tray_with_returns_on_four_sides_is_eight_folds(tmp_path):
    """The 03M shape: two horizontal and two vertical axes each side of the centre."""
    bends = []
    for off in (42.8, 85.6, 1164.4, 1207.2):
        bends.append(((105, off), (1145, off)))      # horizontal
        bends.append(((off, 105), (off, 1145)))      # vertical
    flat = extract_flat_pattern_data(_flat(tmp_path, "T-01_1.5mm_MS_REV_A.DXF", SQUARE, bends))
    assert flat["bend_count"] == 8
    assert len(flat["bend_axes"]) == 8
    assert sorted({a["angle_deg"] for a in flat["bend_axes"]}) == [0.0, 90.0]


def test_one_vertical_fold_is_one_fold_and_cannot_rule_folding_out(tmp_path):
    """The silent strip: one bend line running up the sheet read as a measured zero."""
    path = _flat(tmp_path, "V-01_2mm_MS.DXF", [(0, 0), (300, 0), (300, 120), (0, 120)],
                 [((150, 0), (150, 120))])
    flat = extract_flat_pattern_data(path)
    assert flat["bend_count"] == 1
    assert flat["bend_positions_x_mm"] == [150.0]
    assert dxf_can_rule_out_folding(path, True, flat["bend_count"]) is False


def test_a_bend_line_broken_around_a_cut_out_is_still_one_fold(tmp_path):
    """The rule that was right stays right, in both directions."""
    bends = [((0, 50), (120, 50)), ((180, 50), (300, 50)),         # one horizontal axis, two pieces
             ((200, 0), (200, 20)), ((200, 80.2), (200, 100))]     # one vertical axis, two pieces
    flat = extract_flat_pattern_data(
        _flat(tmp_path, "B-01_2mm_MS.DXF", [(0, 0), (300, 0), (300, 100), (0, 100)], bends))
    assert flat["bend_count"] == 2


def test_a_line_drawn_backwards_is_the_same_axis(tmp_path):
    """Direction is read modulo 180: right-to-left and left-to-right are one fold."""
    bends = [((0, 40), (100, 40)), ((300, 40.1), (150, 40.1))]
    flat = extract_flat_pattern_data(
        _flat(tmp_path, "R-01_2mm_MS.DXF", [(0, 0), (300, 0), (300, 100), (0, 100)], bends))
    assert flat["bend_count"] == 1


def test_a_diagonal_fold_is_counted(tmp_path):
    """Neither horizontal nor vertical: the old reader dropped it in both buckets."""
    flat = extract_flat_pattern_data(
        _flat(tmp_path, "D-01_2mm_MS.DXF", [(0, 0), (200, 0), (200, 200), (0, 200)],
              [((0, 100), (100, 200))]))
    assert flat["bend_count"] == 1
    assert flat["bend_axes"][0]["angle_deg"] == 45.0


def test_two_parallel_folds_apart_are_two(tmp_path):
    flat = extract_flat_pattern_data(
        _flat(tmp_path, "P-01_2mm_MS.DXF", [(0, 0), (300, 0), (300, 100), (0, 100)],
              [((0, 30), (300, 30)), ((0, 70), (300, 70))]))
    assert flat["bend_count"] == 2
    assert flat["bend_positions_mm"] == [30.0, 70.0]


def test_no_bend_layer_lines_is_still_zero(tmp_path):
    flat = extract_flat_pattern_data(
        _flat(tmp_path, "Z-01_2mm_MS.DXF", [(0, 0), (300, 0), (300, 100), (0, 100)], []))
    assert flat["bend_count"] == 0


# ── the revision in the file name ───────────────────────────────────────────────────

@pytest.mark.parametrize("name, rev", [
    ("12693-01-03M_1.5mm_MS_REV_A.DXF", "A"),
    ("12693-01-02M_3mm_MS_REV_A.DXF", "A"),
    ("9376-01-001_MS_1_5mm_revL.DXF", "L"),
    ("12242-01-01M_MS_1_5mm_revD.DXF", "D"),
    ("1097502A01_2mm_ACRY_Rev_B.DXF", "B"),
    ("X-REVIEW_2mm.dxf", None),
    ("1455-C-002_1mm.dxf", None),
])
def test_the_revision_is_read_when_rev_and_its_letter_stand_apart(name, rev):
    assert _parse_filename(Path(name))["revision"] == rev


def test_the_part_number_and_thickness_are_unchanged_by_the_revision_read():
    got = _parse_filename(Path("12693-01-03M_1.5mm_MS_REV_A.DXF"))
    assert got["part_number"] == "12693-01-03M"
    assert got["thickness_mm"] == 1.5
    assert got["material"] == "MILD_STEEL"


# ── the same pack's worktop finish ──────────────────────────────────────────────────
#
# "WORKTOP: LIGHT AGED ZINC WITH WAXED FINISH WRAPPED OVER MRMDF CORE". The plating card's
# cover test asked only whether a card word appeared, and ZINC did, so a decorative aged and
# waxed effect would have been charged at the trade zinc-and-passivate rate per kilo.

import config                                                       # noqa: E402
from estimator import plating_unit_price                            # noqa: E402

_POLICY = config.PLATE_SUBCONTRACT_POLICY


@pytest.mark.parametrize("finish", [
    "LIGHT AGED ZINC WITH WAXED FINISH",
    "antique zinc effect",
    "patinated zinc",
    "Distressed galvanised",
    "zinc, burnished and waxed",
])
def test_a_decorative_zinc_effect_is_not_the_trade_zinc_card(finish):
    unit, note, method = plating_unit_price(18.3, 1, _POLICY, finish, ("12999-01",))
    assert unit is None
    assert method == "subcontract_plating_quote_needed"
    assert note.startswith("DECORATIVE FINISH STATED, NOT PRICED")
    assert "NOT charged" in note


@pytest.mark.parametrize("finish", ["zinc passivate", "BRIGHT ZINC PLATING", "galvanised",
                                    "ZINC PLATED, PACKAGED IN PAIRS"])
def test_trade_zinc_still_takes_the_card(finish):
    unit, _, method = plating_unit_price(2.4, 6, _POLICY, finish, ("12999-01",))
    assert method == "subcontract_plating_indicative"
    assert unit == 15.83
