"""Howard Thurley on 1176-02 (22 Sep 2026): a part longer than one hanging bar occupies several
on the powder line. "420mm bar size (+15mm) component size as 860mm long length allowed 2.0476
Bars + Additional bar for spacing / movement of component so 3 bars @ 106 per hour AI at 319 per
hour." The method lives in config.POWDER_HANGING; these pin his worked example (D-308).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import wb_populate as wp  # noqa: E402


def _part(pn, length, width=72.0, qty=1):
    return {"part_number": pn, "quantity": qty,
            "material_estimate": {"blank_length_mm": length, "blank_width_mm": width}}


def test_howards_worked_example_is_three_bars_and_106_an_hour():
    assert wp.powder_bars_per_piece(845.0) == 3          # (845 + 15) / 420 = 2.0476 -> 2, +1
    rate, working = wp.powder_hanging_throughput([_part("1176-02-01", 845.0)])
    assert round(rate) == 106
    assert "3 bars" in working and "Howard" in working


def test_a_part_that_fits_on_one_bar_keeps_the_size_band():
    assert wp.powder_bars_per_piece(300.0) is None
    assert wp.powder_hanging_throughput([_part("SMALL", 300.0, 200.0)]) is None


def test_the_longer_side_is_the_one_it_hangs_by():
    assert wp.powder_bars_per_piece(wp._part_long_length_mm(_part("P", 72.0, 845.0))) == 3


def test_parts_sharing_a_row_combine_as_one_true_rate():
    rate, _ = wp.powder_hanging_throughput([_part("LONG", 845.0), _part("SHORT", 300.0, 100.0)])
    # 2 pieces over 3 + 1 bars: 319 * 2 / 4, not the mean of 106 and 319
    assert round(rate, 1) == round(319 * 2 / 4, 1)


def test_rounding_up_is_one_setting(monkeypatch):
    rule = dict(config.POWDER_HANGING, rounding="up")
    assert wp.powder_bars_per_piece(845.0, rule) == 4


def test_off_means_off():
    assert wp.powder_bars_per_piece(845.0, dict(config.POWDER_HANGING, enabled=False)) is None


def test_every_figure_is_in_config_with_its_source():
    rule = config.POWDER_HANGING
    for k in ("line_bars_per_hour", "bar_pitch_mm", "clearance_mm", "spacing_bars",
              "stated_by", "stated_on", "source_job"):
        assert rule.get(k) not in (None, ""), k
