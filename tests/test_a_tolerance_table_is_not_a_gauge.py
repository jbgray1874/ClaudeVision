"""A drawing's tolerance table is not the part's gauge.

8352's title block carries a general tolerance table — 0.5/1.0/1.5/2.0 mm by length band. The
extractor picked the FIRST thickness as the primary, so 0.5mm became the title block's stated
gauge on six mild-steel parts. The model (3.0/4.0/1.2mm) then had to overrule each one, and every
overrule raised a gauge-disagreement flag that was pure noise — the 0.5mm was never a gauge.

The band is stripped only when the WHOLE of it is present, so a LONE 2.0mm gauge still survives.
What is left, at or above the sheet floor, is the stated gauge; nothing left means the title
block named no thickness of its own.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import extractor_patterns as ep  # noqa: E402


def test_a_full_tolerance_table_yields_no_gauge():
    """THE 8352 CASE. The whole band and nothing else — the title block stated no thickness."""
    assert ep._primary_thickness_mm(["0.5", "1.0", "1.5", "2.0"]) is None


def test_a_real_gauge_beside_the_band_survives():
    """A stated 3mm gauge printed alongside the tolerance table is the gauge; the band is not."""
    assert ep._primary_thickness_mm(["0.5", "1.0", "1.5", "2.0", "3.0"]) == 3.0


def test_a_lone_gauge_that_happens_to_be_a_band_value_is_kept():
    """2.0 on its own is an ordinary gauge — it is only a tolerance value when the whole band is
    present. Stripping it unconditionally would erase real 2mm parts."""
    assert ep._primary_thickness_mm(["2.0"]) == 2.0
    assert ep._primary_thickness_mm(["1.5"]) == 1.5


def test_sub_floor_noise_is_not_a_gauge():
    """A 0.5 on its own, below the sheet floor, is tolerance/line-weight bleed, not a 0.5mm part."""
    assert ep._primary_thickness_mm(["0.5"]) is None


def test_a_plain_gauge_list_takes_the_first_plausible():
    assert ep._primary_thickness_mm(["3.0", "6.0"]) == 3.0


def test_no_thicknesses_is_none():
    assert ep._primary_thickness_mm([]) is None
    assert ep._primary_thickness_mm(None) is None


def test_the_extractor_uses_the_tolerance_aware_picker():
    """Wired: the title block's primary thickness is chosen by the filter, not first-or-none."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "extractor_patterns.py"),
               encoding="utf-8").read()
    assert '"primary_thickness_mm": _primary_thickness_mm(thicknesses)' in src
